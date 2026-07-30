import { afterEach, describe, expect, test, rs } from "@rstest/core";

import {
  closeConnectWindow,
  openConnectUrl,
  prepareConnectWindow,
} from "@/core/channels/open-connect-url";

type PopupStub = {
  closed: boolean;
  close: ReturnType<typeof rs.fn>;
  location: {
    replace: ReturnType<typeof rs.fn>;
  };
  opener: unknown;
};

/**
 * 封装测试或脚本中的可复用操作，使调用处能够明确复用 stubWindow 的约定。

 */

function stubWindow(openResult: PopupStub | null) {
  const assign = rs.fn();
  const open = rs.fn(() => openResult);
  rs.stubGlobal("window", {
    open,
    location: { assign },
  });
  return { assign, open };
}

/**
 * 构造测试所需的稳定夹具，使调用处能够明确复用 makePopup 的约定。

 */

function makePopup(): PopupStub {
  return {
    closed: false,
    close: rs.fn(),
    location: { replace: rs.fn() },
    opener: {},
  };
}

afterEach(() => {
  rs.unstubAllGlobals();
});

describe("channel connect window helpers", () => {
  /**
   * 覆盖“opens a blank tab synchronously and detaches opener”这一可观察行为，防止相关边界在重构后回归。
   */
  test("opens a blank tab synchronously and detaches opener", () => {
    const popup = makePopup();
    const { open } = stubWindow(popup);

    const prepared = prepareConnectWindow();

    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(prepared).toBe(popup);
    expect(popup.opener).toBeNull();
  });

  /**
   * 覆盖“navigates a prepared popup without opening another window”这一可观察行为，防止相关边界在重构后回归。

   */

  test("navigates a prepared popup without opening another window", () => {
    const popup = makePopup();
    const { assign, open } = stubWindow(null);

    openConnectUrl(
      "https://t.me/deerflow_bot?start=state",
      popup as unknown as Window,
    );

    expect(open).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
    expect(popup.location.replace).toHaveBeenCalledWith(
      "https://t.me/deerflow_bot?start=state",
    );
  });

  /**
   * 覆盖“falls back to current-window navigation when no popup is available”这一可观察行为，防止相关边界在重构后回归。

   */

  test("falls back to current-window navigation when no popup is available", () => {
    const { assign } = stubWindow(null);

    openConnectUrl("https://t.me/deerflow_bot?start=state");

    expect(assign).toHaveBeenCalledWith(
      "https://t.me/deerflow_bot?start=state",
    );
  });

  /**
   * 覆盖“closes a prepared popup on connect failure”这一可观察行为，防止相关边界在重构后回归。

   */

  test("closes a prepared popup on connect failure", () => {
    const popup = makePopup();

    closeConnectWindow(popup as unknown as Window);

    expect(popup.close).toHaveBeenCalled();
  });
});
