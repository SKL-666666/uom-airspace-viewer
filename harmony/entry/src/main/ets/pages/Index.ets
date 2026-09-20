import { webview } from '@kit.ArkWeb';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN = 0x0000;

/* 默认加载线上站点（GitHub Pages 支持 HTTP Range，PMTiles 可在纯静态环境
   下工作）。若在设置里填了本地服务地址，则优先用本地地址 —— 本地服务
   能提供 /diag/* 诊断端点，排查问题更方便。 */
const REMOTE_URL = 'https://skl-666666.github.io/uom-airspace-viewer/index.html';
const LOCAL_URL = 'http://127.0.0.1:8080/index.html';

@Entry
@Component
struct Index {
  controller: webview.WebviewController = new webview.WebviewController();
  @State url: string = REMOTE_URL;
  @State loading: boolean = true;
  @State useLocal: boolean = false;

  private reload(): void {
    this.url = this.useLocal ? LOCAL_URL : REMOTE_URL;
    this.loading = true;
  }

  build() {
    Stack({ alignContent: Alignment.Top }) {
      Web({ src: this.url, controller: this.controller })
        .javaScriptAccess(true)
        .domStorageAccess(true)          // 页面用 localStorage 存底图 key
        .fileAccess(true)
        .imageAccess(true)
        .onlineImageAccess(true)
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
            hilog.error(DOMAIN, 'UOMViewer', '加载错误: %{public}s', event.error.getErrorInfo());
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

      // 右下角悬浮按钮：切换线上/本地地址并重新加载
      Row({ space: 8 }) {
        Text(this.useLocal ? '本地' : '线上')
          .fontSize(11)
          .fontColor('#6B7280')
        Button('切换来源')
          .fontSize(11)
          .height(30)
          .backgroundColor('#FFFFFF')
          .fontColor('#16181D')
          .borderWidth(1)
          .borderColor('#DFE2E7')
          .onClick(() => {
            this.useLocal = !this.useLocal;
            this.reload();
          })
      }
      .padding({ left: 10, right: 6, top: 6, bottom: 6 })
      .backgroundColor('#FFFFFFE6')
      .borderRadius(8)
      .borderWidth(1)
      .borderColor('#DFE2E7')
      .margin({ top: 12, right: 12 })
      .position({ x: '100%', y: 0 })
      .translate({ x: -180 })
    }
    .width('100%')
    .height('100%')
  }
}
