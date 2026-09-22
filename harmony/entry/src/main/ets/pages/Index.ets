import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN = 0x0000;

/**
 * 主页面：加载【应用内置】的网页与数据。
 *
 * 不再依赖 GitHub Pages —— 实测在中国大陆首次建连要 10~15 秒，
 * 而无人机场景常在野外没有稳定网络，所以数据全部内置进 HAP。
 *
 * 页面地址是 http://127.0.0.1:<port>/index.html。
 * 端口由 EntryAbility 启动的 RangeHttpServer 分配后写入 AppStorage，
 * 这里读出来拼成 URL。
 *
 * 为什么不能直接加载 rawfile://：
 *   PMTiles 依赖 HTTP Range（206）按需读字节，rawfile:// 不走 HTTP，
 *   拿不到 206，地图会一片空白。详见 common/RangeHttpServer.ets 的说明。
 */
@Entry
@Component
struct Index {
  controller: webview.WebviewController = new webview.WebviewController();
  @StorageLink('localPort') localPort: number = -1;
  @State url: string = '';
  @State loading: boolean = true;

  aboutToAppear(): void {
    this.resolveUrl();
  }

  private resolveUrl(): void {
    if (this.localPort > 0) {
      this.url = 'http://127.0.0.1:' + this.localPort + '/index.html';
      hilog.info(DOMAIN, 'UOMViewer', '加载内置数据 %{public}s', this.url);
    }
  }

  build() {
    Stack({ alignContent: Alignment.Center }) {
      if (this.url) {
        Web({ src: this.url, controller: this.controller })
          .javaScriptAccess(true)
          .domStorageAccess(true)          // 页面用 localStorage 存设置与收藏
          .fileAccess(true)
          .imageAccess(true)
          .onlineImageAccess(true)         // 底图是第三方瓦片，需要联网
          .mixedMode(MixedMode.All)
          .zoomAccess(true)
          .horizontalScrollBarAccess(false)
          .verticalScrollBarAccess(false)
          .width('100%')
          .height('100%')
          .onPageEnd(() => {
            this.loading = false;
            hilog.info(DOMAIN, 'UOMViewer', '页面加载完成');
          })
          .onErrorReceive((event) => {
            if (event && event.error) {
              hilog.error(DOMAIN, 'UOMViewer', '加载错误 %{public}s',
                          event.error.getErrorInfo());
            }
          })

        if (this.loading) {
          Column({ space: 12 }) {
            LoadingProgress().width(48).height(48).color('#2C5F5A')
            Text('正在加载地图…').fontSize(13).fontColor('#6B7280')
          }
          .width('100%')
          .height('100%')
          .justifyContent(FlexAlign.Center)
          .backgroundColor('#EFF1F4')
        }
      } else {
        // 服务还没起来：显示等待状态，而不是白屏
        Column({ space: 12 }) {
          LoadingProgress().width(48).height(48).color('#2C5F5A')
          Text(this.localPort < 0 ? '本地数据服务启动失败' : '正在启动本地数据服务…')
            .fontSize(13)
            .fontColor('#6B7280')
        }
        .width('100%')
        .height('100%')
        .justifyContent(FlexAlign.Center)
        .backgroundColor('#EFF1F4')
      }
    }
    .width('100%')
    .height('100%')
  }
}
