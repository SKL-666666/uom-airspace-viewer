import { webview } from '@kit.ArkWeb';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { StorageBridge } from '../common/StorageBridge';

const DOMAIN = 0x0000;

/* javaScriptProxy 的参数结构。
   ArkTS 不允许裸对象字面量（arkts-no-untyped-obj-literals），
   必须显式声明类型 —— 编译器直接报了这个错。
   字段与 SDK 里的 JavaScriptProxy 接口一一对应，这里本地声明一份，
   避免依赖 SDK 内部类型路径。 */
interface StorageProxyOptions {
  object: object;
  name: string;
  methodList: string[];
  controller: WebviewController;
}

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
  /* 定位权限结果由 EntryAbility 写入 AppStorage，这里同步读取 */
  @StorageLink('locationGranted') locationGranted: boolean = false;
  /* 由 EntryAbility 初始化后放进 AppStorage 的存储桥 */
  @StorageLink('storageBridge') storageBridge: StorageBridge | null = null;
  @State url: string = '';
  @State loading: boolean = true;
  /** 页面请求定位但没权限时，显示一条可关闭的提示 */
  @State showPermissionHint: boolean = false;

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
          .domStorageAccess(true)          // 页面仍可用 localStorage（网页版走它）
          /* 注入原生存储桥，名为 UomNativeStorage —— 与 Android 端同名，
             页面代码不需要区分平台。
             为什么需要：localStorage 按 origin 隔离，而页面从
             http://127.0.0.1:<port>/ 加载，端口变化会让 origin 变化，
             API key / 收藏 / 主题字号就全部读不到。
             注意：这里【不能】把它列进 asyncMethodList —— 
             页面是按同步方式读取的（启动时就要定底图和字号），
             列为异步会让页面拿到 Promise。 */
          .javaScriptProxy({
            object: this.storageBridge as object,
            name: 'UomNativeStorage',
            methodList: ['getItem', 'setItem', 'removeItem', 'keys'],
            controller: this.controller,
          } as StorageProxyOptions)
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
          /* 关键：ArkWeb 里的 navigator.geolocation 会先问宿主
             "这个源能不能用定位"。不接这个回调 = 不应答 = 当作拒绝，
             于是页面拿到权限错误 —— 而系统权限可能已经给了，
             所以现象非常像"App 没申请权限"，很难倒推。
             接住它：已授权就放行；未授权则拒绝并提示去设置里开。 */
          .onGeolocationShow((event) => {
            if (!event) return;
            const origin: string = event.origin;
            const granted: boolean = this.locationGranted;
            hilog.info(DOMAIN, 'UOMViewer',
                       '页面请求定位 origin=%{public}s granted=%{public}s',
                       origin, String(granted));
            try {
              // invoke(origin, allow, retain)
              // retain=false：不把这次决定写进系统，避免用户改了系统设置后
              // 这里还留着旧结果。
              event.geolocation.invoke(origin, granted, false);
            } catch (e) {
              const err = e as BusinessError;
              hilog.error(DOMAIN, 'UOMViewer', '放行定位失败 %{public}s',
                          JSON.stringify(err));
            }
            if (!granted) {
              this.showPermissionHint = true;
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

      if (this.showPermissionHint) {
        // 定位被拒时的提示。
        // 做成可关闭的浮层而不是 Toast：用户需要照着去系统设置里操作，
        // Toast 一闪就没了，来不及看。
        Row({ space: 8 }) {
          Text('未授予定位权限。可在 设置 → 应用 → 权限 里开启，'
             + '也可以直接在搜索框输入坐标查询')
            .fontSize(12)
            .fontColor('#7A5413')
            .layoutWeight(1)
          Button('知道了')
            .fontSize(11)
            .height(28)
            .backgroundColor('#FFFFFF')
            .fontColor('#16181D')
            .borderWidth(1)
            .borderColor('#F0DCB6')
            .onClick(() => { this.showPermissionHint = false; })
        }
        .width('92%')
        .padding(12)
        .backgroundColor('#FDF3E2')
        .borderRadius(10)
        .borderWidth(1)
        .borderColor('#F0DCB6')
        .position({ x: '4%', y: '4%' })
      }
    }
    .width('100%')
    .height('100%')
  }
}
