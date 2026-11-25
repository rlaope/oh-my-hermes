import { describe, expect, it } from "vitest";
import { koText } from "./textLang";

describe("koText", () => {
  it("marks Korean text, mixed with Latin words, URLs and Han characters", () => {
    expect(koText("연결됨")).toBe("ko");
    expect(koText("Grafana에서 Kubernetes 설정을 확인했습니다. https://example.com")).toBe("ko");
    expect(koText("漢字 섞인 한국어")).toBe("ko");
  });
  it("leaves other text unmarked: English, Japanese, Chinese, empty", () => {
    expect(koText("Connected")).toBeUndefined();
    expect(koText("今日はKubernetesの設定を確認しました。")).toBeUndefined();
    expect(koText("今天检查了Kubernetes的配置。")).toBeUndefined();
    expect(koText("")).toBeUndefined();
    expect(koText(undefined)).toBeUndefined();
  });
  it("Japanese with a Korean word in it stays Japanese", () => {
    expect(koText("「안녕」は韓国語のあいさつです")).toBeUndefined();
  });
});
