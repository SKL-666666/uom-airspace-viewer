import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { RangeHttpServer } from '../common/RangeHttpServer';

const DOMAIN = 0x0000;

/* 本地服务实例。放在 Ability 层而不是页面里，是为了让它与 Ability 同生命周期：
   页面重建（旋转、切后台回来）不应导致服务重启，否则数据通道会断。
   页面通过 AppStorage 读端口。 */
const server: RangeHttpServer = new RangeHttpServer();

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    hilog.info(DOMAIN, 'UOMViewer', 'Ability onCreate');
  }

  onDestroy(): void {
    hilog.info(DOMAIN, 'UOMViewer', 'Ability onDestroy');
    server.stop();
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    hilog.info(DOMAIN, 'UOMViewer', 'Ability onWindowStageCreate');

    // 先起本地数据服务，把端口放进 AppStorage，页面构建时读取。
    // 页面加载 http://127.0.0.1:<port>/index.html —— 与本地开发用 serve.py 同构，
    // 因此 index.html 不需要为移动端做任何特化。
    server.init(this.context).then(() => server.start()).then((port: number) => {
      if (port > 0) {
        AppStorage.setOrCreate('localPort', port);
        hilog.info(DOMAIN, 'UOMViewer', '数据服务端口 %{public}d', port);
      } else {
        AppStorage.setOrCreate('localPort', -1);
        hilog.error(DOMAIN, 'UOMViewer', '数据服务启动失败');
      }
    }).catch((e: Object) => {
      AppStorage.setOrCreate('localPort', -1);
      hilog.error(DOMAIN, 'UOMViewer', '数据服务异常 %{public}s', JSON.stringify(e));
    });

    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(DOMAIN, 'UOMViewer', 'loadContent 失败: %{public}s', JSON.stringify(err));
        return;
      }
      // 全屏：地图页面不需要状态栏占地方
      try {
        const win = windowStage.getMainWindowSync();
        win.setWindowLayoutFullScreen(true);
      } catch (e) {
        hilog.warn(DOMAIN, 'UOMViewer', '设置全屏失败: %{public}s', JSON.stringify(e));
      }
    });
  }

  onWindowStageDestroy(): void {
  }

  onForeground(): void {
  }

  onBackground(): void {
  }
}
