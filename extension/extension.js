// Screenshot Helper — 超薄 GNOME 49 扩展，导出 dbus 接口
// 让后台服务（如 dayscope.service）可以无侵入截屏。
//
// 走扩展这条路径的原因：
// - mutter 49 把 org.gnome.Shell.Screenshot 列为"private API"，
//   拒绝所有外部进程直接调用（mss/portal/gnome-screenshot 都被拒）。
// - 扩展运行在 mutter 进程内，享有同源信任，可直接调 Meta.Screenshot。
// - 我们导出自定义 dbus 接口 cn.local.ScreenshotHelper.Screenshot。

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DBUS_NAME = 'cn.local.ScreenshotHelper';
const DBUS_PATH = '/cn/local/ScreenshotHelper';

const IFACE_XML = `
<node>
  <interface name="cn.local.ScreenshotHelper">
    <method name="Screenshot">
      <arg type="b" direction="in" name="include_cursor"/>
      <arg type="b" direction="in" name="flash"/>
      <arg type="s" direction="in" name="filename"/>
      <arg type="b" direction="out" name="success"/>
      <arg type="s" direction="out" name="filename_used"/>
    </method>
    <method name="ScreenshotArea">
      <arg type="i" direction="in" name="x"/>
      <arg type="i" direction="in" name="y"/>
      <arg type="i" direction="in" name="width"/>
      <arg type="i" direction="in" name="height"/>
      <arg type="b" direction="in" name="flash"/>
      <arg type="s" direction="in" name="filename"/>
      <arg type="b" direction="out" name="success"/>
      <arg type="s" direction="out" name="filename_used"/>
    </method>
    <method name="ListScreens">
      <arg type="as" direction="out" name="screens"/>
    </method>
  </interface>
</node>
`;

const HelperIface = Gio.DBusInterfaceInfo.new_for_xml(IFACE_XML);

class ScreenshotHelper {
    constructor() {
        this._screenshot = new Shell.Screenshot();
        this._dbusImpl = Gio.DBusExportedObject.wrapJSObject(HelperIface, this);
        this._dbusImpl.export(Gio.DBus.session, DBUS_PATH);
        Gio.DBus.session.own_name(
            DBUS_NAME,
            Gio.BusNameOwnerFlags.REPLACE,
            null,
            null
        );
        console.log(`[screenshot-helper] enabled; bus=${DBUS_NAME} path=${DBUS_PATH}`);
    }

    _openStream(filename) {
        // mutter 49 的 Shell.Screenshot 需要 GOutputStream，不接受文件路径字符串
        const file = Gio.File.new_for_path(filename);
        return file.replace(null, false, Gio.FileCreateFlags.NONE, null);
    }

    _screenshotFull(include_cursor, flash, filename) {
        return new Promise((resolve, reject) => {
            try {
                const stream = this._openStream(filename);
                this._screenshot.screenshot(
                    !!include_cursor,
                    stream,
                    (obj, result) => {
                        try {
                            const [success, area] = this._screenshot.screenshot_finish(result);
                            resolve([!!success, filename, area]);
                        } catch (e) {
                            reject(e);
                        }
                    }
                );
            } catch (e) {
                reject(e);
            }
        });
    }

    _screenshotArea(x, y, w, h, flash, filename) {
        return new Promise((resolve, reject) => {
            try {
                const stream = this._openStream(filename);
                this._screenshot.screenshot_area(
                    x, y, w, h,
                    stream,
                    (obj, result) => {
                        try {
                            const [success, area] = this._screenshot.screenshot_area_finish(result);
                            resolve([!!success, filename, area]);
                        } catch (e) {
                            reject(e);
                        }
                    }
                );
            } catch (e) {
                reject(e);
            }
        });
    }

    // dbus: Screenshot(b, b, s) -> (b, s)
    ScreenshotAsync(params, invocation) {
        const [include_cursor, flash, filename] = params;
        this._screenshotFull(include_cursor, flash, filename)
            .then(([success, filename_used]) => {
                invocation.return_value(
                    GLib.Variant.new('(bs)', [success, filename_used])
                );
            })
            .catch((e) => {
                logError(e, 'ScreenshotHelper.Screenshot failed');
                invocation.return_error_literal(
                    Gio.IOErrorEnum, Gio.IOErrorEnum.FAILED, e.message
                );
            });
    }

    // dbus: ScreenshotArea(i, i, i, i, b, s) -> (b, s)
    ScreenshotAreaAsync(params, invocation) {
        const [x, y, w, h, flash, filename] = params;
        this._screenshotArea(x, y, w, h, flash, filename)
            .then(([success, filename_used]) => {
                invocation.return_value(
                    GLib.Variant.new('(bs)', [success, filename_used])
                );
            })
            .catch((e) => {
                logError(e, 'ScreenshotHelper.ScreenshotArea failed');
                invocation.return_error_literal(
                    Gio.IOErrorEnum, Gio.IOErrorEnum.FAILED, e.message
                );
            });
    }

    // dbus: ListScreens() -> as
    ListScreensAsync(params, invocation) {
        try {
            const n = global.display.get_n_monitors();
            const out = [];
            for (let i = 0; i < n; i++) {
                const r = global.display.get_monitor_geometry(i);
                out.push(`${r.width}x${r.height}+${r.x}+${r.y}`);
            }
            invocation.return_value(GLib.Variant.new('(as)', [out]));
        } catch (e) {
            logError(e, 'ScreenshotHelper.ListScreens failed');
            invocation.return_error_literal(
                Gio.IOErrorEnum, Gio.IOErrorEnum.FAILED, e.message
            );
        }
    }

    destroy() {
        this._dbusImpl?.unexport_from_connection(Gio.DBus.session);
    }
}

export default class ScreenshotHelperExtension extends Extension {
    enable() {
        this._helper = new ScreenshotHelper();
    }

    disable() {
        this._helper?.destroy();
        this._helper = null;
    }
}
