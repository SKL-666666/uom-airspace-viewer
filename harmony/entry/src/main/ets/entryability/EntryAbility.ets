import { AbilityConstant, UIAbility, Want, abilityAccessCtrl, Permissions } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { RangeHttpServer } from '../common/RangeHttpServer';
import { StorageBridge } from '../common/StorageBridge';

const DOMAIN = 0x0000;

/* 本地服务实例。放在 Ability 层而不是页面里，是为了让它与 Ability 同生命周期：
   页面重建（旋转、切后台回来）不应导致服务重启，否则数据通道会断。
   页面通过 AppStorage 读端口。 */
const server: RangeHttpServer = new RangeHttpServer();

/* 用户数据的原生存储。放在 Ability 层与 Ability 同生命周期，
   页面重建不会导致重新初始化（重新初始化会短暂读不到数据）。 */
const storage: StorageBridge = new StorageBridge();

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

    // 先申请定位权限。
    // 为什么在 Ability 里申请而不是等用户点"定位"再申请：
    //   ① ArkWeb 的定位回调（onGeolocationShow）在页面发起请求时触发，
    //      如果那一刻才弹权限框，用户点完还要再等一轮，而页面没有反馈；
    //   ② 权限申请需要 UIAbilityContext，页面拿到的 context 类型不同。
    // 申请结果不影响启动 —— 用户拒绝也能正常用，只是定位按钮会提示去设置里开。
    this.requestLocationPermission();

    /* 先初始化用户数据存储，再起服务、加载页面 ——
       顺序很重要：页面启动时就要读 API key / 主题 / 字号，
       存储没就绪的话首屏会用默认值，然后数据"看起来又丢了"。 */
    storage.init(this.context).then(() => {
      AppStorage.setOrCreate('storageBridge', storage);
      hilog.info(DOMAIN, 'UOMViewer', '用户数据存储已就绪');
    }).catch((e: Object) => {
      AppStorage.setOrCreate('storageBridge', storage);   // 仍注入，退化为内存态
      hilog.error(DOMAIN, 'UOMViewer', '用户数据存储初始化异常 %{public}s', JSON.stringify(e));
    });

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

  /**
   * 申请定位权限。
   * LOCATION 与 APPROXIMATELY_LOCATION 必须【成对】申请 ——
   * 只申请 LOCATION 会被系统直接拒绝（API 9 起的要求），
   * 这也是"H5 定位报权限问题"的常见原因之一。
   */
  private requestLocationPermission(): void {
    try {
      const atManager = abilityAccessCtrl.createAtManager();
      const perms: Permissions[] = [
        'ohos.permission.LOCATION',
        'ohos.permission.APPROXIMATELY_LOCATION',
      ];
      atManager.requestPermissionsFromUser(this.context, perms)
        .then((result) => {
          // authResults: 0 表示已授权，-1 表示拒绝
          const granted = result.authResults.every((v: number) => v === 0);
          hilog.info(DOMAIN, 'UOMViewer', '定位权限申请结果 granted=%{public}s', String(granted));
          AppStorage.setOrCreate('locationGranted', granted);
        })
        .catch((e: Object) => {
          hilog.warn(DOMAIN, 'UOMViewer', '定位权限申请异常 %{public}s', JSON.stringify(e));
          AppStorage.setOrCreate('locationGranted', false);
        });
    } catch (e) {
      hilog.error(DOMAIN, 'UOMViewer', '申请定位权限失败 %{public}s', JSON.stringify(e));
      AppStorage.setOrCreate('locationGranted', false);
    }
  }

  onWindowStageDestroy(): void {
  }

  onForeground(): void {
  }

  onBackground(): void {
  }
}
