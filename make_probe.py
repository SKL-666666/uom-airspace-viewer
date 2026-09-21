# 生成一个带自检探针的 index.html 副本，交给无头 Chrome 跑。
#
# 为什么需要它：静态检查（check_ids / check_refs / check_order）只能证明
# "名字对得上、语法能过"，证明不了"页面真的跑起来了"。这一轮把标记、样式、
# 事件全动了一遍，必须真在浏览器里执行一次。
#
# 做法：复制 index.html -> _probe.html，注入
#   ① <head> 里的错误收集器（window.onerror / unhandledrejection）
#   ② </body> 前的驱动脚本：按顺序点击各个按钮、在地图上触发点击查询，
#      最后把观测结果写进 <pre id="__probe">，配合 chrome --dump-dom 读出来。
# 只读产物，不改动 index.html。
#
# 用法: python make_probe.py
#       chrome --headless=new --dump-dom http://127.0.0.1:8080/_probe.html
import io, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
src = io.open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()

HEAD_INJECT = """<script>
/* ---- 探针①：错误收集 ---- */
window.__errs = [];
window.addEventListener('error', function(e){
  window.__errs.push('ERR ' + e.message + ' @' + (e.filename || '') + ':' + (e.lineno || 0));
});
window.addEventListener('unhandledrejection', function(e){
  var r = e.reason;
  window.__errs.push('REJ ' + ((r && (r.message || r.toString())) || '?'));
});
</script>
"""

BODY_INJECT = """<script>
/* ---- 探针②：驱动 + 观测 ---- */
(function(){
  var L_ = [];
  // 观测结果既写进 DOM，也随手 POST 到 /__diag 落到 diag.log。
  // 原因：无头浏览器跑完可能被虚拟时间/超时打断，只靠 --dump-dom 会拿不到结果；
  // 有了这条通道，即使中途退出也能看到已经跑过的步骤。
  function post(){
    try {
      fetch('/__diag', { method: 'POST', body: 'PROBE\\n' + L_.join('\\n') });
    } catch(e){}
  }
  function log(k, v){ L_.push(k + '=' + v); post(); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  // 等条件成立（最多 ms 毫秒）。固定 sleep 很难拿捏：短了测不到结果，
  // 长了白等；而且一旦某步变慢，结论就不可信了。
  async function waitFor(fn, ms){
    var t0 = Date.now();
    while (Date.now() - t0 < ms){
      try { if (fn()) return true; } catch(e){}
      await sleep(120);
    }
    return false;
  }
  async function step(name, fn){
    try { await fn(); }
    catch(e){ L_.push('STEP_FAIL ' + name + ': ' + ((e && e.message) || e)); }
  }
  // 顶层 const 在经典脚本里属于全局词法作用域，后续脚本可直接引用
  function q(s){ return document.querySelector(s); }
  function has(s){ return !!document.querySelector(s); }

  (async function(){
    await sleep(3500);

    // ---- 1. 启动状态 ----
    log('loading_display', q('#loading') ? q('#loading').style.display : 'NO');
    log('bdVer', q('#bdVer') ? q('#bdVer').textContent : 'NO');
    log('bdUom', q('#bdUom') ? q('#bdUom').textContent : 'NO');
    log('zoom_bottomleft', has('.leaflet-bottom.leaflet-left .leaflet-control-zoom'));
    log('zoom_topleft_dup', has('.leaflet-top.leaflet-left .leaflet-control-zoom'));
    log('scale', has('.leaflet-control-scale'));
    log('baseSel_options', document.querySelectorAll('#baseSel option').length);
    log('baseUsel_btn', q('#baseUsel .usel-btn') ? q('#baseUsel .usel-btn').textContent : 'NO');
    log('baseUsel_opts', document.querySelectorAll('#baseUsel .usel-opt').length);
    log('themeUsel_btn', q('#themeUsel .usel-btn') ? q('#themeUsel .usel-btn').textContent : 'NO');
    log('fontUsel_btn', q('#fontUsel .usel-btn') ? q('#fontUsel .usel-btn').textContent : 'NO');
    log('side_sections', document.querySelectorAll('#side .sec').length);
    log('prov_options', document.querySelectorAll('#provSel option').length);
    log('tiles', document.querySelectorAll('.leaflet-tile').length);
    log('dji_sub', q('#djiN') ? q('#djiN').textContent : 'NO');
    log('aboutUom', q('#aboutUomDate') ? q('#aboutUomDate').textContent : 'NO');
    log('root_font', getComputedStyle(document.documentElement).fontSize);
    log('body_font', getComputedStyle(document.body).fontSize);
    log('font_family', getComputedStyle(document.body).fontFamily.split(',')[0]);
    log('side_default_hidden', q('#side') ? !q('#side').classList.contains('on') : 'NO');
    log('result_default_hidden', q('#result') ? !q('#result').classList.contains('on') : 'NO');
    /* 窄屏会走另一套布局（抽屉 + 隐藏部分状态），所以这几项在两种窗口尺寸下
       取值不同 —— 用它来验证移动端断点确实生效，而不是"以为生效了"。 */
    log('isMobile', typeof isMobile === 'function' ? isMobile() : 'NO');
    log('viewport', window.innerWidth + 'x' + window.innerHeight);
    log('bdPos_display', getComputedStyle(q('#bdPos')).display);
    log('brand_display', getComputedStyle(q('#brand')).display);
    log('side_width', getComputedStyle(q('#side')).width);
    log('coordBar_display', getComputedStyle(q('#coordBar')).display);
    log('toolbar_tb_size', getComputedStyle(q('#toolbar .tb')).width);
    // 顶部只应剩一个面板入口按钮（原来图层/设置两个，功能重复）
    log('topbar_buttons', document.querySelectorAll('#topbar .tb').length);
    // 底部左下的缩放/比例尺不能和坐标读数或面板打架
    log('zoom_bottom', has('.leaflet-bottom.leaflet-left .leaflet-control-zoom'));
    log('coordbar_overlaps_zoom',   // 期望 false
      (function(){
        var zb = q('.leaflet-bottom.leaflet-left');
        var cb = q('#coordBar');
        if (!zb || !cb || getComputedStyle(cb).display === 'none') return 'skip';
        var a = zb.getBoundingClientRect(), b = cb.getBoundingClientRect();
        return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
      })());
    log('measurePanel_default_hidden', !q('#measurePanel').classList.contains('on'));

    // ---- 2. 点击地图查询（最核心的一条路径）----
    await step('mapclick', async function(){
      map.fire('click', { latlng: L.latLng(39.9087, 116.3975) });
      await sleep(3000);
      log('result_on', q('#result') ? q('#result').classList.contains('on') : 'NO');
      log('resCoord', q('#resCoord') ? q('#resCoord').textContent : 'NO');
      log('resVerdict_cls', q('#resVerdict') ? q('#resVerdict').className : 'NO');
      log('resVerdict_big', q('#resVerdict .big') ? q('#resVerdict .big').textContent : 'NO');
      log('resRows_n', document.querySelectorAll('#resRows .krow').length);
      log('resRows_keys', Array.prototype.map.call(
        document.querySelectorAll('#resRows .krow .k'), function(e){ return e.textContent; }).join('|'));
      log('resDetail_open_default', q('#resDetail') ? q('#resDetail').open : 'NO');
      log('resDetail_rows', document.querySelectorAll('#resDetailRows .krow').length);
      log('resDetail_keys', Array.prototype.map.call(
        document.querySelectorAll('#resDetailRows .krow .k'), function(e){ return e.textContent; }).join('|'));
      // 顶层 let/const 在经典脚本里属于全局词法作用域，探针脚本可直接引用；
      // 用 window.lastResult 是读不到的（它不会挂到 window 上）。
      log('lastResult_ok', !!lastResult);
      log('lastResult_coord', lastResult ? (lastResult.lat.toFixed(4) + ',' + lastResult.lon.toFixed(4)) : 'NONE');
      // preferCanvas:true 时标记与折线画在 canvas 上，DOM 里没有 <path>
      log('canvas_layers', document.querySelectorAll('.leaflet-pane canvas').length);
    });

    // ---- 3. 结果抽屉收起/展开 ----
    await step('grip', async function(){
      q('#resGrip').click();
      await sleep(200);
      log('result_min_after_grip', q('#result').classList.contains('min'));
      q('#resGrip').click();
      await sleep(200);
      log('result_min_toggled_back', !q('#result').classList.contains('min'));
    });

    // ---- 4. 面板开合 ----
    await step('panels', async function(){
      q('#btnLayers').click(); await sleep(150);
      log('side_on_after_layers', q('#side').classList.contains('on'));
      log('btnLayers_on', q('#btnLayers').classList.contains('on'));
      log('side_open_sections', document.querySelectorAll('#side .sec[open]').length);
      q('#cstToggle').click(); await sleep(150);
      log('cstBox_opened', q('#cstBox').style.display === 'block');
      q('#cstToggle').click(); await sleep(150);
      log('cstBox_closed', q('#cstBox').style.display === 'none');
      q('#btnLayers').click(); await sleep(150);
      log('side_off_after_toggle', !q('#side').classList.contains('on'));
      q('#btnFav').click(); await sleep(150);
      log('panelFav_on', q('#panelFav').classList.contains('on'));
      q('#btnData').click(); await sleep(150);
      log('panelData_on', q('#panelData').classList.contains('on'));
      log('panelFav_off', !q('#panelFav').classList.contains('on'));
      q('#dataClose').click(); await sleep(150);
      log('panelData_closed', !q('#panelData').classList.contains('on'));
    });

    // ---- 5. 自定义下拉（1.3）----
    await step('usel', async function(){
      q('#baseUsel .usel-btn').click(); await sleep(150);
      log('baseUsel_open', q('#baseUsel').classList.contains('open'));
      log('baseUsel_list_visible', getComputedStyle(q('#baseUsel .usel-list')).display);
      var opt = document.querySelectorAll('#baseUsel .usel-opt');
      log('baseUsel_opt_first', opt.length ? opt[0].textContent : 'NONE');
      // 选一个高德矢量（GCJ-02），验证坐标系提示联动
      var target = null;
      for (var i = 0; i < opt.length; i++){
        if (opt[i].dataset.value === 'amap_vec') target = opt[i];
      }
      if (target){
        target.click();
        await sleep(1200);
        log('after_amap_baseSel', q('#baseSel').value);
        log('amapWarn_on', q('#amapWarn').classList.contains('on'));
        log('crs_is_gcj', typeof currentBaseCrs === 'function' ? currentBaseCrs() : 'NO');
      }
      // 关掉坐标系提示再恢复（2.5）
      var x = q('#amapWarn [data-close-warn]');
      if (x){
        x.click(); await sleep(200);
        log('amapWarn_after_close', q('#amapWarn').classList.contains('on'));
        log('crsWarnHint_shown', getComputedStyle(q('#crsWarnHint')).display);
        q('#crsWarnShow').click(); await sleep(300);
        log('amapWarn_after_restore', q('#amapWarn').classList.contains('on'));
      }
    });

    // ---- 6. 主题与字号（1.2 / 3.6）----
    await step('theme', async function(){
      themeUi.set('dark', true); await sleep(250);
      log('theme_attr', document.documentElement.dataset.theme);
      log('dark_tx', getComputedStyle(document.documentElement).getPropertyValue('--tx').trim());
      themeUi.set('light', true); await sleep(150);
      log('theme_attr_light', document.documentElement.dataset.theme);
      fontUi.set('large', true); await sleep(200);
      log('root_font_large', getComputedStyle(document.documentElement).fontSize);
      fontUi.set('auto', true); await sleep(150);
      log('root_font_auto', getComputedStyle(document.documentElement).fontSize);
    });

    // ---- 7. 手动刷新（2.1）----
    await step('refresh', async function(){
      var before = document.querySelectorAll('#toast .tst').length;
      q('#btnRefresh').pointerdown && q('#btnRefresh').dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true }));
      await sleep(120);
      q('#btnRefresh').dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
      await sleep(900);
      log('toast_after_refresh', document.querySelectorAll('#toast .tst').length - before);
      var tsts = document.querySelectorAll('#toast .tst .tst-title');
      log('toast_last', tsts.length ? tsts[tsts.length - 1].textContent : 'NONE');
    });

    // ---- 8. 测距/测面（3.1，改成"先选类型 → 画 → 点确定"）----
    await step('measure', async function(){
      q('#btnMeasure').click(); await sleep(250);
      log('measure_panel_on', q('#measurePanel').classList.contains('on'));
      log('measure_ask_visible', getComputedStyle(q('#measureAsk')).display !== 'none');
      log('measure_work_hidden', getComputedStyle(q('#measureWork')).display === 'none');
      log('measure_btn_on', q('#btnMeasure').classList.contains('on'));
      log('dblclickzoom_off', map.doubleClickZoom.enabled() === false);
      log('measure_rect_top', Math.round(q('#measurePanel').getBoundingClientRect().top));
      log('topbar_bottom', Math.round(q('#topbar').getBoundingClientRect().bottom));
      log('measure_under_topbar',
        q('#measurePanel').getBoundingClientRect().top >=
        q('#topbar').getBoundingClientRect().bottom - 1);
      // 侧栏这一步可能还关着（display:none 时矩形是 0,0，判断无意义）—— 显式跳过
      log('side_under_topbar',
        getComputedStyle(q('#side')).display === 'none' ? 'skip(hidden)'
          : q('#side').getBoundingClientRect().top >= q('#topbar').getBoundingClientRect().bottom - 1);

      // 先选类型：测面积
      q('#measureArea').click(); await sleep(200);
      log('measure_work_visible', getComputedStyle(q('#measureWork')).display !== 'none');
      log('measure_kind_label', q('#measureKindLabel').textContent);
      log('measure_big_before', q('#measureBig').textContent);

      map.fire('click', { latlng: L.latLng(39.90, 116.39) }); await sleep(150);
      log('measure_pts_1', measurePts.length);
      log('measure_big_1pt', q('#measureBig').textContent);
      map.fire('click', { latlng: L.latLng(39.95, 116.45) }); await sleep(150);
      map.fire('click', { latlng: L.latLng(39.92, 116.50) }); await sleep(300);
      log('measure_pts_3', measurePts.length);
      log('measure_big_area', q('#measureBig').textContent);
      log('measure_small', q('#measureSmall').textContent);

      // 撤销一点
      q('#measureUndo').click(); await sleep(200);
      log('measure_pts_after_undo', measurePts.length);

      // 补回来再确定
      map.fire('click', { latlng: L.latLng(39.93, 116.48) }); await sleep(250);
      var shown = q('#measureBig').textContent;
      q('#measureOk').click(); await sleep(300);
      log('measure_panel_closed', !q('#measurePanel').classList.contains('on'));
      log('measure_kept_after_ok', measurePts.length);
      log('measure_kept_label_was', shown);
      log('dblclickzoom_restored', map.doubleClickZoom.enabled() === true);
      log('measure_shape_kept', !!measureShape);

      // 再点按钮：清掉上一段并重新问"要测什么"
      q('#btnMeasure').click(); await sleep(250);
      log('measure_cleared_on_reopen', measurePts.length === 0);
      log('measure_ask_again', getComputedStyle(q('#measureAsk')).display !== 'none');
      q('#measureLine').click(); await sleep(150);
      log('measure_kind_line', q('#measureKindLabel').textContent);
      q('#measureCancel').click(); await sleep(250);
      log('measure_panel_closed_after_cancel', !q('#measurePanel').classList.contains('on'));
      log('measure_cleared_after_cancel', measurePts.length === 0);
      log('shape_removed_after_cancel', !measureShape);
    });

    // ---- 9. 收藏（3.2）----
    await step('fav', async function(){
      q('#resFav').click(); await sleep(400);
      log('fav_rows', document.querySelectorAll('#favList .fav-row').length);
      log('fav_text', q('#favList .fav-row .fr-n') ? q('#favList .fav-row .fr-n').textContent : 'NONE');
    });

    // ---- 10. 批量查询（3.4）----
    await step('bulk', async function(){
      q('#bulkIn').value = '天安门,39.9087,116.3975\\n浦东 31.2304,121.4737\\n坏行 xxx';
      q('#bulkRun').click();
      await sleep(25000);
      log('bulk_rows', document.querySelectorAll('#bulkOut .bulk-tbl tbody tr').length);
      log('bulk_sum', q('#bulkOut .bulk-sum') ? q('#bulkOut .bulk-sum').textContent.trim() : 'NONE');
      log('bulk_btn_back', q('#bulkRun').textContent);
    });

    // ---- 11. 自检（2.6）----
    await step('diag', async function(){
      q('#diagView').click();
      await sleep(25000);
      var t = q('#diagOut') ? q('#diagOut').value : '';
      log('diag_display', q('#diagOut') ? q('#diagOut').style.display : 'NO');
      log('diag_has_selfcheck', t.indexOf('视野瓦片自检') >= 0);
      log('diag_has_probe', t.indexOf('底图探活') >= 0);
      log('diag_has_worker_stat', t.indexOf('Worker 统计') >= 0);
      log('diag_head', t.split('\\n').slice(0, 6).join(' / '));
      log('diag_tail', t.split('\\n').slice(-3).join(' / '));
    });

    // ---- 12. 搜索（1.1 / 2.3 / 2.9）----
    // 用户环境里配了天地图 tk，所以在线通道是活的；无头环境默认没有 tk。
    // 这里装一个假 tk + 拦掉 fetch 返回真实形状的响应，把【用户那条路径】跑起来。
    await step('search_online', async function(){
      var REAL = {
        count: 958, prompt: [{type:0,admins:'北京市'}], resultType: 1, lineData: [],
        keyWord: '首都机场', status: { cndesc:'服务正常', infocode: 1000 },
        pois: [
          { address:'北京市顺义区', phone:'', poiType:0, name:'首都机场',
            source:'0', hotPointID:'', lonlat:'116.406621,40.072647' },
          { address:'北京市朝阳区', phone:'', poiType:0, name:'首都机场T3',
            source:'0', hotPointID:'', lonlat:'116.585,40.053' }
        ]
      };
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      window.fetch = function(u, o){
        if (String(u).indexOf('api.tianditu.gov.cn') >= 0){
          return Promise.resolve({ ok:true, status:200,
            text: function(){ return Promise.resolve(JSON.stringify(REAL)); } });
        }
        return realFetch.apply(this, arguments);
      };

      // 用【真实输入事件】驱动，不直接调用函数 —— 要测的就是这条接线
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      searchInput.value = '首都机场';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      await waitFor(function(){
        return document.querySelectorAll('#searchResults .sres').length > 0;
      }, 15000);

      log('so_input_val', searchInput.value);
      log('so_rows', document.querySelectorAll('#searchResults .sres').length);
      log('so_display', getComputedStyle(q('#searchResults')).display);
      log('so_first_name', q('#searchResults .sres .sr-n') ? q('#searchResults .sres .sr-n').textContent : 'NONE');
      log('so_first_addr', q('#searchResults .sres .sr-d') ? q('#searchResults .sres .sr-d').textContent : 'NONE');
      log('so_box_class', q('#searchResults').className);
      log('so_cache', geoCache.size);
      // 点一条，看是否定位并查询
      var row = q('#searchResults .sres');
      if (row){
        row.click();
        await waitFor(function(){
          var b = q('#resVerdict .big');
          return b && b.textContent && b.textContent !== '查询中…';
        }, 30000);
        log('so_after_pick_closed', getComputedStyle(q('#searchResults')).display === 'none');
        log('so_after_pick_result', q('#resVerdict .big') ? q('#resVerdict .big').textContent : 'NONE');
        log('so_after_pick_coord', q('#resCoord') ? q('#resCoord').textContent : 'NONE');
      }
      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
    });

    // ---- 12a1. 网络层失败（Failed to fetch）要给出可操作提示 ----
    await step('search_netfail', async function(){
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      window.fetch = function(u){
        if (String(u).indexOf('tianditu') >= 0){
          return Promise.reject(new TypeError('Failed to fetch'));
        }
        return realFetch.apply(this, arguments);
      };
      geoCache.clear();
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      searchInput.value = '首都机场';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      await waitFor(function(){ return !!q('#searchResults .sempty'); }, 20000);
      var note = q('#searchResults .sempty') ? q('#searchResults .sempty').textContent : '';
      log('nf_note', note.slice(0, 160).split(String.fromCharCode(10)).join(' / '));
      log('nf_says_network', /网络/.test(note));
      log('nf_mentions_tile_probe', /瓦片域名/.test(note));
      log('nf_gives_actions', /代理|扩展|防火墙|高德/.test(note));
      log('nf_not_blaming_key', !/key 无效|非法key/.test(note));
      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
      geoCache.clear();
      searchInput.value = '';
      closeSearch();
    });

    // ---- 12a2. 宽泛关键词（顶层无 pois 的聚合响应）不能报成故障 ----
    await step('search_toobroad', async function(){
      var AGG = { count: 2196, prompt: [{type:0,admins:''}], resultType: 1,
                  keyWord: '机场', statistics: { total: 2196 },
                  status: { cndesc:'服务正常', infocode: 1000 } };
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      window.fetch = function(u){
        if (String(u).indexOf('tianditu') >= 0){
          return Promise.resolve({ ok:true, status:200,
            text: function(){ return Promise.resolve(JSON.stringify(AGG)); } });
        }
        return realFetch.apply(this, arguments);
      };
      geoCache.clear();
      searchInput.value = '';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      searchInput.value = '机场';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      await waitFor(function(){ return !!q('#searchResults .sempty'); }, 15000);
      var note = q('#searchResults .sempty') ? q('#searchResults .sempty').textContent : '';
      log('tb_display', getComputedStyle(q('#searchResults')).display);
      log('tb_note', note.slice(0, 140));
      log('tb_says_too_broad', /太多|太宽泛|更具体/.test(note));
      log('tb_not_reported_as_failure', !/解析|失败/.test(note));
      log('tb_rows', document.querySelectorAll('#searchResults .sres').length);
      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
      geoCache.clear();
      searchInput.value = '';
      closeSearch();
    });

    // ---- 12b0. 中文输入法：组字期间不能搜拼音 ----
    // 这是"诊断能搜到、搜索框搜不到"的根因所在：
    // 用拼音打字时输入框的值先是拼音，若不区分就会拿拼音去在线搜 → 0 条。
    await step('search_ime', async function(){
      var REAL = {
        count: 958, resultType: 1, lineData: [], keyWord: '首都机场',
        status: { cndesc:'服务正常', infocode: 1000 },
        pois: [{ address:'北京市顺义区', name:'首都机场', lonlat:'116.406621,40.072647' }]
      };
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      var queries = [];
      window.fetch = function(u){
        if (String(u).indexOf('tianditu') >= 0){
          var q = decodeURIComponent(String(u).split('postStr=')[1].split('&')[0]);
          try { queries.push(JSON.parse(q).keyWord); } catch(e){ queries.push('?'); }
          return Promise.resolve({ ok:true, status:200,
            text: function(){ return Promise.resolve(JSON.stringify(REAL)); } });
        }
        return realFetch.apply(this, arguments);
      };
      geoCache.clear();
      closeSearch();
      searchInput.value = '';

      // ① 模拟拼音组字：compositionstart -> 值变成拼音 -> input(isComposing)
      searchInput.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      searchInput.value = 'shoudujichang';
      searchInput.dispatchEvent(new CompositionEvent('input',
        { bubbles: true, isComposing: true }));
      await sleep(600);                       // 超过防抖时间，看会不会去搜拼音
      log('ime_queries_during_compose', queries.length);
      log('ime_no_pinyin_query', queries.indexOf('shoudujichang') < 0);
      log('ime_box_hidden_while_composing',
          getComputedStyle(q('#searchResults')).display === 'none');

      // ② 组字期间按 Enter（选词）：绝不能被我们 preventDefault 吃掉
      var enterEv = new KeyboardEvent('keydown',
        { key:'Enter', bubbles: true, cancelable: true, isComposing: true });
      searchInput.dispatchEvent(enterEv);
      log('ime_enter_not_prevented', !enterEv.defaultPrevented);

      // ③ 提交：compositionend + 值变成中文
      searchInput.value = '首都机场';
      searchInput.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
      await waitFor(function(){
        return document.querySelectorAll('#searchResults .sres').length > 0;
      }, 15000);
      log('ime_rows_after_commit', document.querySelectorAll('#searchResults .sres').length);
      log('ime_queries', queries.join(','));
      log('ime_queried_chinese', queries.indexOf('首都机场') >= 0);
      log('ime_name', q('#searchResults .sres .sr-n') ? q('#searchResults .sres .sr-n').textContent : 'NONE');
      log('ime_display', getComputedStyle(q('#searchResults')).display);

      // ④ 组字结束后 Enter 必须能选结果
      var ev2 = new KeyboardEvent('keydown', { key:'Enter', bubbles: true, cancelable: true });
      searchInput.dispatchEvent(ev2);
      await sleep(600);
      log('ime_enter_selects', q('#resCoord') ? q('#resCoord').textContent : 'NONE');

      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
      geoCache.clear();
      searchInput.value = '';
      closeSearch();
    });

    // ---- 12b2. 把真实响应喂进【runSearch 本身】----
    // 之前只测到 geoTianditu 这一层（诊断按钮就是直接调它）。
    // 用户看到的是 runSearch 的结果，所以必须让真实响应走完整条链路。
    // 如果他一路正常而这一路不行，差异就一定在 runSearch 里。
    await step('search_runsearch_real', async function(){
      var REAL = {
        count: 958, prompt: [{type:0, admins:'北京市'}], resultType: 1, lineData: [],
        keyWord: '首都机场', status: { cndesc:'服务正常', infocode: 1000 },
        pois: [
          { address:'北京市顺义区', phone:'', poiType:0, name:'首都机场',
            source:'0', hotPointID:'', lonlat:'116.406621,40.072647' },
          { address:'北京市朝阳区', phone:'', poiType:0, name:'首都机场T3',
            source:'0', hotPointID:'', lonlat:'116.585,40.053' }
        ]
      };
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      window.fetch = function(u){
        if (String(u).indexOf('tianditu') >= 0){
          return Promise.resolve({ ok:true, status:200,
            text: function(){ return Promise.resolve(JSON.stringify(REAL)); } });
        }
        return realFetch.apply(this, arguments);
      };
      geoCache.clear();
      try { await runSearch('首都机场'); } catch(e){ log('rs_THROW', (e&&e.message)||e); }
      await sleep(400);
      log('rs_rows', document.querySelectorAll('#searchResults .sres').length);
      log('rs_display', getComputedStyle(q('#searchResults')).display);
      log('rs_html', q('#searchResults').innerHTML.slice(0, 200));
      log('rs_searchItems', searchItems.length);
      log('rs_cache', geoCache.size);
      log('rs_seq', searchSeq);
      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
      geoCache.clear();
    });

    // ---- 12c. 并发/重复输入的竞态：打字稍慢时会不会把结果丢掉 ----
    await step('search_race', async function(){
      var REAL = {
        count: 958, resultType: 1, lineData: [], keyWord: '首都机场',
        status: { cndesc:'服务正常', infocode: 1000 },
        pois: [{ address:'北京市顺义区', name:'首都机场', lonlat:'116.406621,40.072647' }]
      };
      CONFIG.keys.tdt = 'FAKE_TK_FOR_PROBE______________';
      var realFetch = window.fetch;
      var calls = 0;
      window.fetch = function(u){
        if (String(u).indexOf('api.tianditu.com') >= 0 || String(u).indexOf('api.tianditu.gov.cn') >= 0){
          calls++;
          // 故意慢一点，制造"第一次请求还没回来，第二次已经发起"的窗口
          return new Promise(function(res){
            setTimeout(function(){
              res({ ok:true, status:200,
                    text: function(){ return Promise.resolve(JSON.stringify(REAL)); } });
            }, 300);
          });
        }
        return realFetch.apply(this, arguments);
      };
      geoCache.clear();
      // 模拟用户"打字稍慢但有重复输入"：连续两次触发同一个词
      runSearch('首都机场');
      await sleep(80);
      runSearch('首都机场');
      await waitFor(function(){
        return document.querySelectorAll('#searchResults .sres').length > 0;
      }, 8000).then(function(got){ log('race_got_rows', got); });
      log('race_rows', document.querySelectorAll('#searchResults .sres').length);
      log('race_display', getComputedStyle(q('#searchResults')).display);
      log('race_note', q('#searchResults .sempty') ? q('#searchResults .sempty').textContent.slice(0,80) : 'NONE');
      window.fetch = realFetch;
      CONFIG.keys.tdt = '';
      geoCache.clear();
    });

    await step('search', async function(){
      // 坐标解析（离线，必须可用）
      searchInput.value = '39.9087,116.3975';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(400);
      log('search_open_coord', q('#searchResults').classList.contains('on'));
      log('search_rows_coord', document.querySelectorAll('#searchResults .sres').length);
      log('search_first_coord', q('#searchResults .sres .sr-n') ? q('#searchResults .sres .sr-n').textContent : 'NONE');
      log('search_kind_coord', q('#searchResults .sres .sr-k') ? q('#searchResults .sres .sr-k').textContent : 'NONE');

      // 省市名（离线）
      searchInput.value = '广东';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      await sleep(400);
      log('search_rows_prov', document.querySelectorAll('#searchResults .sres').length);
      log('search_first_prov', q('#searchResults .sres .sr-n') ? q('#searchResults .sres .sr-n').textContent : 'NONE');

      // 走一次完整跳转
      var row = q('#searchResults .sres');
      if (row){
        row.click();
        await sleep(2500);
        log('search_closed_after_pick', !q('#searchResults').classList.contains('on'));
        log('result_on_after_search', q('#result').classList.contains('on'));
        log('coord_after_search', q('#resCoord') ? q('#resCoord').textContent : 'NONE');
      }
      // 在线地理编码（有无 tk 都要能优雅收场）
      searchInput.value = '首都机场';
      searchInput.dispatchEvent(new Event('input', { bubbles: true }));
      // 先确认防抖确实触发了
      await sleep(200);
      log('debounce_pending', (typeof searchDebounce !== 'undefined' && searchDebounce) ? 'yes' : 'no');
      /* 不能一看到 .sempty 就断言"搜完了" —— 那是 loading 中间态。
         必须等到出现真正的 .sres 行，或者等到搜索真的结束
         （runSearch 结束后：有 sres，或有 sempty 但【没有 .on 之外的中间态】）。
         这里用"输入值未变 + debounce 已结束 + 没有 pending 的查询"来判定。 */
      await waitFor(function(){
        return document.querySelectorAll('#searchResults .sres').length > 0;
      }, 15000);
      log('geo_rows', document.querySelectorAll('#searchResults .sres').length);
      log('geo_note', q('#searchResults .sempty') ? q('#searchResults .sempty').textContent.slice(0, 160) : 'NONE');
      /* 有内容就必须可见 —— 这是这次的核心缺陷，单独断言 */
      var boxEl = q('#searchResults');
      if (boxEl && boxEl.innerHTML.length > 0){
        log('box_visible_when_filled',
            getComputedStyle(boxEl).display !== 'none');
      } else {
        log('box_visible_when_filled', 'skip(empty)');
      }
      log('geo_box_on', q('#searchResults').classList.contains('on'));
      log('geo_cache_size', geoCache ? geoCache.size : 'NO');
      /* 直接跑一遍 runSearch 并观察各中间量 —— 与诊断按钮走的是不同路径，
         两条路径一个通一个不通时，必须把这条路径的每一步都摊开。 */
      try {
        const r = await geoSearch('首都机场');
        log('geoSearch_items', r.items.length);
        log('geoSearch_used', r.used || 'NONE');
        log('geoSearch_errors', (r.errors || []).join(' | ').slice(0, 200));
        log('geoSearch_noneCfg', !!r.noneConfigured);
      } catch(e){ log('geoSearch_THROW', (e && e.message) || e); }
      try {
        const loc = localSearch('首都机场');
        log('localSearch_n', loc.length);
      } catch(e){ log('localSearch_THROW', (e && e.message) || e); }
      /* 关键：直接问"真实输入触发的那一次"到底渲染了什么。
         renderSearch 会写 innerHTML；如果它是空的，说明输入回调根本没跑到那里。 */
      log('box_html_len', q('#searchResults') ? q('#searchResults').innerHTML.length : 'NO');
      log('box_class', q('#searchResults') ? q('#searchResults').className : 'NO');
      /* 走一遍真实的 renderSearch（本地结果 + 在线结果都要能正确显示） */
      renderSearch([{ kind:'geo', name:'测试地点', lat:39.9, lon:116.4, addr:'北京市' }], null);
      log('render_online_visible', getComputedStyle(q('#searchResults')).display !== 'none');
      log('render_online_rows', document.querySelectorAll('#searchResults .sres').length);
      log('render_online_addr', q('#searchResults .sr-d') ? q('#searchResults .sr-d').textContent : 'NONE');
      closeSearch();
      log('render_closed_after_close', getComputedStyle(q('#searchResults')).display === 'none');
      log('box_display', q('#searchResults') ? getComputedStyle(q('#searchResults')).display : 'NO');
      log('searchItems_len', typeof searchItems !== 'undefined' ? searchItems.length : 'NO');
      log('searchInput_value', searchInput.value);
      log('searchClear_hidden', document.getElementById('searchClear').hidden);
      log('topbar_display', getComputedStyle(q('#topbar')).display);
      log('topbar_z', getComputedStyle(q('#topbar')).zIndex);
      log('box_z', q('#searchResults') ? getComputedStyle(q('#searchResults')).zIndex : 'NO');
      log('topbar_in_doc', !!q('#topbar'));
      /* 再走一次完整的 runSearch，看渲染这一步 */
      try {
        await runSearch('首都机场');
        await sleep(500);
        log('after_runSearch_rows', document.querySelectorAll('#searchResults .sres').length);
        log('after_runSearch_note', q('#searchResults .sempty') ? q('#searchResults .sempty').textContent.slice(0, 160) : 'NONE');
      } catch(e){ log('runSearch_THROW', (e && e.message) || e); }
    });

    // ---- 12b. 地名搜索连通性测试（无头环境没有 key，应正确报告"未配置"）----
    await step('geotest', async function(){
      q('#diagGeo').click();
      await waitFor(function(){ return q('#diagOut') && q('#diagOut').value.length > 0; }, 30000);
      var t = q('#diagOut') ? q('#diagOut').value : '';
      log('geotest_shown', t.length > 0);
      log('geotest_lines', t.split(String.fromCharCode(10)).slice(0, 5).join(' ~ '));
      log('geotest_mentions_nokey', /未配置 key|都没配 key/.test(t));
      log('geotest_no_key_leak', /[A-Za-z0-9]{24,}/.test(t) ? 'LEAK?' : 'ok');
      log('geotest_has_shape_dump', /原始返回结构/.test(t));
      var dump = '';
      try { dump = await tdtRawDump('首都机场'); } catch(e){ dump = 'ERR ' + e.message; }
      log('shapedump', String(dump).split(String.fromCharCode(10)).join(' ~ ').slice(0, 300));
      report('PROBE_SHAPEDUMP', String(dump).slice(0, 1500));
    });

    // ---- 13. 定位错误分类（2.2）+ 剪贴板（2.9）----
    await step('geo_clip', async function(){
      log('secure_context', window.isSecureContext);
      log('geo_api', !!navigator.geolocation);
      q('#btnLoc').click();
      // 无头 Chrome 没有定位源，预期走"拿不到位置"而不是"被拒绝"这条分支；
      // 关键是能看到【区分开的提示】，而不是原来那句把两种原因混在一起的废话。
      await waitFor(function(){ return !!q('#toast .tst .tst-title'); }, 15000);
      var titles = document.querySelectorAll('#toast .tst .tst-title');
      log('geo_toast', titles.length ? titles[titles.length - 1].textContent : 'NONE');
      var details = document.querySelectorAll('#toast .tst .tst-detail');
      log('geo_detail_has_guidance',
        details.length ? /系统定位|权限|坐标输入/.test(details[details.length - 1].textContent) : false);

      var copied = false;
      try { copied = await copyText('uom-probe'); }
      catch(e){ log('copy_throw', (e && e.message) || e); }
      log('copy_returns_bool', typeof copied === 'boolean');
    });

    // ---- 14. 导出（3.3，不真下载，只验证不抛错）----
    await step('export', async function(){
      var called = 0;
      var origCreate = document.createElement.bind(document);
      document.createElement = function(t){
        var el = origCreate(t);
        if (t === 'a'){ el.click = function(){ called++; }; }
        return el;
      };
      try { exportKML(); } catch(e){ log('kml_err', (e && e.message) || e); }
      try { exportGeoJSON(); } catch(e){ log('geo_err', (e && e.message) || e); }
      document.createElement = origCreate;
      log('export_downloads', called);
      log('imported_n', importedFeatures.length);
    });

    log('final_errs', JSON.stringify(window.__errs));
    post();

    var pre = document.createElement('pre');
    pre.id = '__probe';
    pre.textContent = L_.join('\\n');
    document.body.appendChild(pre);
    // 完成信号：CDP 客户端轮询这个变量，比 --dump-dom 的虚拟时间可靠得多
    window.__probeText = pre.textContent;
  })();
})();
</script>
"""

# ① 注入 head 探针（放在 charset 之后，确保最先安装错误钩子）
assert '<meta charset="utf-8">' in src
head_pos = src.index('<meta charset="utf-8">') + len('<meta charset="utf-8">')
out = src[:head_pos] + '\n' + HEAD_INJECT + src[head_pos:]

# ② 注入驱动脚本（主脚本之后、</body> 之前）
body_pos = out.rindex('</body>')
out = out[:body_pos] + BODY_INJECT + out[body_pos:]

dst = os.path.join(ROOT, '_probe.html')
io.open(dst, 'w', encoding='utf-8').write(out)
print('已生成 ' + dst + '（%d 字节）' % len(out))
