import { describe, expect, it } from "vitest";
import { koText } from "./textLang";

describe("koText", () => {
  it("marks Korean text, with English product names, URLs and the odd Han character in it", () => {
    expect(koText("연결됨")).toBe("ko");
    expect(koText("네")).toBe("ko");
    expect(koText("Grafana에서 Kubernetes 설정을 확인하고 Terraform으로 Prometheus 알림을 고쳤습니다. https://example.com/a/b/c")).toBe("ko");
    expect(koText("漢字 섞인 한국어 문장입니다")).toBe("ko");
    expect(koText("PR #3211 리뷰 반영했어요")).toBe("ko");
  });
  it("leaves English, Japanese, Chinese and empty text unmarked", () => {
    expect(koText("Connected")).toBeUndefined();
    expect(koText("今日はKubernetesの設定を確認しました。")).toBeUndefined();
    expect(koText("今天检查了Kubernetes的配置。")).toBeUndefined();
    expect(koText("")).toBeUndefined();
    expect(koText(undefined)).toBeUndefined();
  });
  it("one Korean word in another language does not make the text Korean", () => {
    expect(koText("The Korean word for hello is 안녕, and you say it to friends and family every day.")).toBeUndefined();
    expect(koText("韩语的“你好”写作“안녕”，朋友之间常用。")).toBeUndefined();
    expect(koText("「안녕」は韓国語のあいさつです")).toBeUndefined();
  });
  it("Korean inside code or a URL does not count", () => {
    expect(koText("Print a greeting:\n\n```python\nprint('안녕하세요 여러분 반갑습니다')\n```\n\nThat prints it.")).toBeUndefined();
    expect(koText("Run `echo 안녕하세요` in the shell.")).toBeUndefined();
    expect(koText("See https://ko.wikipedia.org/wiki/한국어 for more.")).toBeUndefined();
  });
  it("counts kana letters only: the middle dot and the long mark are shared punctuation", () => {
    expect(koText("한국어・일본어")).toBe("ko");
    expect(koText("한국어ー일본어")).toBe("ko");
  });
});
