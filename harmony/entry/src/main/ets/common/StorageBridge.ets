import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { BusinessError } from '@kit.BasicServicesKit';

const DOMAIN = 0x0000;

/**
 * 网页端用户数据的原生存储桥（HarmonyOS）。
 *
 * 解决什么问题：
 *   localStorage 按 origin 隔离。移动端页面从 http://127.0.0.1:<port>/ 加载，
 *   端口变化 → origin 变化 → API key、收藏点、主题字号全部读不到。
 *   用户看到的是"切后台回来数据没了"。
 *   写进应用私有目录（Preferences）就与 origin 无关。
 *
 * 关键：方法必须能被【同步】调用。
 *   ArkWeb 的 javaScriptProxy 默认就是同步的 —— 只有列在 asyncMethodList
 *   里的方法才是异步。所以这里不要把这些方法列进 asyncMethodList，
 *   否则页面拿到的是 Promise，而页面代码是按同步读取写的
 *   （启动时就要定下用哪个底图、哪个字号）。
 *
 * 内存缓存：
 *   Preferences 的读取是异步 API，而页面要同步拿值。
 *   所以启动时先把全部数据读进内存，之后 getItem 直接读内存；
 *   写入时同时更新内存与落盘。这也让读取没有 IO 开销。
 */
export class StorageBridge {

  private store: preferences.Preferences | null = null;
  /** 同步读取用的内存镜像 */
  private cache: Map<string, string> = new Map<string, string>();
  private ready: boolean = false;

  /** 单个值的长度上限（防止页面写入超大内容撑爆存储） */
  private static readonly MAX_VALUE_LEN: number = 512 * 1024;
  private static readonly MAX_KEY_LEN: number = 128;

  /**
   * 初始化：把已有数据载入内存。
   * 必须在加载页面前完成，否则页面读到的会是空值。
   */
  async init(ctx: common.UIAbilityContext): Promise<void> {
    try {
      this.store = await preferences.getPreferences(ctx, 'uom_user_data');
      const all: Object = await this.store.getAll();
      const map = all as Record<string, string>;
      for (const k of Object.keys(map)) {
        const v = map[k];
        if (typeof v === 'string') this.cache.set(k, v);
      }
      this.ready = true;
      hilog.info(DOMAIN, 'UOMViewer', '存储桥就绪，载入 %{public}d 项', this.cache.size);
    } catch (e) {
      const err = e as BusinessError;
      hilog.error(DOMAIN, 'UOMViewer', '存储桥初始化失败 %{public}s', JSON.stringify(err));
      // 初始化失败不阻断启动：退化为"本次会话内有效"，页面仍可用
      this.ready = false;
    }
  }

  private validKey(k: string): boolean {
    return !!k && k.length > 0 && k.length <= StorageBridge.MAX_KEY_LEN;
  }

  /** 读。同步返回，找不到返回 null。 */
  getItem(key: string): string | null {
    if (!this.validKey(key)) return null;
    if (!this.cache.has(key)) return null;
    return this.cache.get(key) as string;
  }

  setItem(key: string, value: string): void {
    if (!this.validKey(key) || value === null || value === undefined) return;
    const v = String(value);
    if (v.length > StorageBridge.MAX_VALUE_LEN) {
      hilog.warn(DOMAIN, 'UOMViewer', '值过大，拒绝写入 %{public}s (%{public}d)',
                 key, v.length);
      return;
    }
    this.cache.set(key, v);
    if (!this.store) return;
    try {
      this.store.putSync(key, v);
      // flush 是异步的，但不阻塞调用方；失败只影响落盘，内存已更新
      this.store.flush().catch((e: BusinessError) => {
        hilog.warn(DOMAIN, 'UOMViewer', '落盘失败 %{public}s', JSON.stringify(e));
      });
    } catch (e) {
      const err = e as BusinessError;
      hilog.error(DOMAIN, 'UOMViewer', '写入失败 %{public}s %{public}s',
                  key, JSON.stringify(err));
    }
  }

  removeItem(key: string): void {
    if (!this.validKey(key)) return;
    this.cache.delete(key);
    if (!this.store) return;
    try {
      this.store.deleteSync(key);
      this.store.flush().catch(() => { /* 忽略 */ });
    } catch (e) {
      const err = e as BusinessError;
      hilog.warn(DOMAIN, 'UOMViewer', '删除失败 %{public}s %{public}s',
                 key, JSON.stringify(err));
    }
  }

  /**
   * 列出所有键，返回 JSON 数组字符串。
   * 用 JSON 而不是分隔符拼接：键名可能含任意字符，拼接会在键名含分隔符时解析错。
   */
  keys(): string {
    const arr: string[] = [];
    this.cache.forEach((_v: string, k: string) => { arr.push(k); });
    return JSON.stringify(arr);
  }
}
