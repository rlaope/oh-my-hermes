import { describe, expect, it } from "vitest";
import {
  allowVoice,
  canRecord,
  clock,
  insertTranscript,
  micFailure,
  osOf,
  pickMime,
  RECORD_MAX_BYTES,
  RECORD_MAX_MS,
  RECORD_TYPES,
  VOICE_OK_KEY,
  voiceAllowed,
  voiceFailure,
} from "./voice";
import { readAloud, stopSpeech, voiceInfoOnce } from "./speech";
import type { VoiceInfo, VoiceSpeech } from "../../lib/protocol";

const memory = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};

describe("the recording type", () => {
  it("takes the first type the webview records, in Hermes Desktop's order", () => {
    expect(RECORD_TYPES).toEqual(["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg", "audio/wav"]);
    expect(pickMime(() => true)).toBe("audio/webm;codecs=opus");
    // WKWebView on macOS records AAC in MP4
    expect(pickMime((t) => t === "audio/mp4")).toBe("audio/mp4");
    expect(pickMime((t) => t.startsWith("audio/ogg"))).toBe("audio/ogg;codecs=opus");
    expect(pickMime(() => false)).toBe("");
    expect(
      pickMime(() => {
        throw new Error("no");
      }),
    ).toBe("");
  });

  it("can record only with both getUserMedia and MediaRecorder", () => {
    const nav = (gum: unknown) => ({ mediaDevices: gum ? { getUserMedia: gum } : undefined }) as unknown as Navigator;
    expect(canRecord({ navigator: nav(() => null), MediaRecorder: function MediaRecorder() {} })).toBe(true);
    expect(canRecord({ navigator: nav(undefined), MediaRecorder: function MediaRecorder() {} })).toBe(false);
    expect(canRecord({ navigator: nav(() => null) })).toBe(false);
    expect(canRecord({})).toBe(false);
  });

  it("stops at 3 minutes or 20 MB, under Hermes' 25 MB", () => {
    expect(RECORD_MAX_MS).toBe(180_000);
    expect(RECORD_MAX_BYTES).toBe(20 * 1024 * 1024);
    expect(RECORD_MAX_BYTES).toBeLessThan(25 * 1024 * 1024);
    expect(clock(0)).toBe("0:00");
    expect(clock(65_400)).toBe("1:05");
    expect(clock(RECORD_MAX_MS)).toBe("3:00");
  });
});

describe("a transcript in the draft", () => {
  it("goes in at the caret with a space where words would run together", () => {
    expect(insertTranscript("", 0, 0, " hello there ")).toEqual({ insert: "hello there", text: "hello there", caret: 11 });
    expect(insertTranscript("Please", 6, 6, "check the logs")).toEqual({ insert: " check the logs", text: "Please check the logs", caret: 21 });
    expect(insertTranscript("Please  now", 7, 7, "check").text).toBe("Please check now");
    expect(insertTranscript("Please now", 6, 6, "check")).toEqual({ insert: " check", text: "Please check now", caret: 12 });
    expect(insertTranscript("startend", 5, 5, "middle").text).toBe("start middle end");
    // over a selection, which it replaces
    expect(insertTranscript("say THIS please", 4, 8, "that").text).toBe("say that please");
    // no space before closing punctuation, none beside a line break
    expect(insertTranscript("Done", 4, 4, ".").text).toBe("Done.");
    expect(insertTranscript("one\n", 4, 4, "two").text).toBe("one\ntwo");
    expect(insertTranscript("hi", 0, 0, "Oh").text).toBe("Oh hi");
  });

  it("puts no space between Japanese or Chinese characters, and a space in Korean", () => {
    expect(insertTranscript("今日は", 3, 3, "晴れです").text).toBe("今日は晴れです");
    expect(insertTranscript("我想", 2, 2, "问一下").text).toBe("我想问一下");
    expect(insertTranscript("안녕하세요", 5, 5, "반가워요").text).toBe("안녕하세요 반가워요");
  });

  it("keeps a caret outside the text inside it", () => {
    expect(insertTranscript("abc", 99, 99, "d").text).toBe("abc d");
    expect(insertTranscript("abc", -3, -3, "z").text).toBe("z abc");
  });
});

describe("the first-use notice", () => {
  it("is remembered per bot and per use on this computer", () => {
    const store = memory();
    expect(voiceAllowed("mic", "kami", store)).toBe(false);
    allowVoice("mic", "kami", store);
    expect(voiceAllowed("mic", "kami", store)).toBe(true);
    expect(voiceAllowed("read", "kami", store)).toBe(false);
    expect(voiceAllowed("mic", "friren", store)).toBe(false);
    allowVoice("mic", "kami", store);
    expect(JSON.parse(store.m.get(VOICE_OK_KEY)!)).toEqual({ mic: ["kami"], read: [] });
  });

  it("reads a broken entry as nothing allowed, and a storage that refuses keeps nothing", () => {
    const store = memory();
    store.m.set(VOICE_OK_KEY, "{not json");
    expect(voiceAllowed("read", "kami", store)).toBe(false);
    store.m.set(VOICE_OK_KEY, JSON.stringify({ read: "kami", mic: [3, "kami"] }));
    expect(voiceAllowed("read", "kami", store)).toBe(false);
    expect(voiceAllowed("mic", "kami", store)).toBe(true);
    const refusing = { getItem: () => null, setItem: () => { throw new Error("quota"); } };
    expect(() => allowVoice("read", "kami", refusing)).not.toThrow();
    expect(voiceAllowed("read", "kami", null)).toBe(false);
  });
});

describe("what a failure says", () => {
  it("puts the bridge's code under its own headline and keeps Hermes' words", () => {
    expect(voiceFailure({ code: "voice_no_provider", message: "No STT provider available. Install faster-whisper" })).toEqual({
      head: "voice.errNoProvider",
      said: "No STT provider available. Install faster-whisper",
    });
    expect(voiceFailure({ code: "voice_disabled", message: "x" }).head).toBe("voice.errDisabled");
    expect(voiceFailure({ code: "voice_not_ready", message: "x" }).head).toBe("voice.errNotReady");
    expect(voiceFailure({ code: "voice_unsupported", message: "x" }).head).toBe("voice.errUnsupported");
    expect(voiceFailure({ code: "voice_too_large", message: "x" }).head).toBe("voice.errTooLarge");
    expect(voiceFailure({ code: "voice_https", message: "x" }).head).toBe("voice.errHttps");
    expect(voiceFailure({ code: "voice_timeout", message: "x" }).head).toBe("voice.errTimeout");
    expect(voiceFailure({ code: "remote_only", message: "x" }).head).toBe("voice.offRemote");
    expect(voiceFailure({ code: "something_new", message: "x" }).head).toBe("voice.errFailed");
    expect(voiceFailure("boom")).toEqual({ head: "voice.errFailed", said: "" });
  });

  it("says where to allow the microphone on each system", () => {
    const denied = { name: "NotAllowedError" };
    expect(micFailure(denied, "mac")).toEqual({ head: "voice.micDenied", hint: "voice.micAllowMac" });
    expect(micFailure(denied, "windows")).toEqual({ head: "voice.micDenied", hint: "voice.micAllowWindows" });
    expect(micFailure(denied, "linux")).toEqual({ head: "voice.micDenied", hint: "voice.micAllowLinux" });
    expect(micFailure({ name: "NotFoundError" }, "mac").head).toBe("voice.micNone");
    expect(micFailure({ name: "NotReadableError" }, "mac").head).toBe("voice.micBusy");
    expect(micFailure({ name: "NotSupportedError" }, "mac").head).toBe("voice.noApi");
    expect(micFailure(new Error("x"), "mac").head).toBe("voice.micFailed");
    expect(osOf("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15")).toBe("mac");
    expect(osOf("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/131.0")).toBe("windows");
    expect(osOf("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15")).toBe("linux");
  });
});

describe("voice.info", () => {
  it("is asked once per bot, and again after a failed ask", async () => {
    const info = { supported: true } as VoiceInfo;
    let asked = 0;
    const ask = async () => {
      asked += 1;
      if (asked === 1) throw { code: "disconnected" };
      return info;
    };
    await expect(voiceInfoOnce("solo", ask)).rejects.toEqual({ code: "disconnected" });
    await Promise.resolve();
    expect(await voiceInfoOnce("solo", ask)).toBe(info);
    expect(await voiceInfoOnce("solo", ask)).toBe(info);
    expect(asked).toBe(2);
  });
});

describe("reading aloud", () => {
  it("asks for each part in order and stops fetching when stopped", async () => {
    const asked: number[] = [];
    const speak = (_text: string, part: number): Promise<VoiceSpeech> => {
      asked.push(part);
      // empty parts: nothing to play, so no audio element is needed here
      return Promise.resolve({ part, parts: 3, cut: false, text_max: 20000, empty: true });
    };
    const run = readAloud("text", speak, () => {});
    await run.done;
    expect(asked).toEqual([0, 1, 2]);

    asked.length = 0;
    let release: () => void = () => {};
    const slow = (_text: string, part: number): Promise<VoiceSpeech> => {
      asked.push(part);
      return new Promise((res) => (release = () => res({ part, parts: 5, cut: false, text_max: 20000, empty: true })));
    };
    const second = readAloud("text", slow, () => {});
    stopSpeech();
    release();
    await second.done;
    expect(asked).toEqual([0]);
  });

  it("a second read aloud stops the first", async () => {
    const asked: string[] = [];
    let release: () => void = () => {};
    const first = readAloud("one", (text, part) => {
      asked.push(`${text}:${part}`);
      return new Promise((res) => (release = () => res({ part, parts: 4, cut: false, text_max: 20000, empty: true })));
    }, () => {});
    const second = readAloud("two", (text, part) => {
      asked.push(`${text}:${part}`);
      return Promise.resolve({ part, parts: 1, cut: false, text_max: 20000, empty: true });
    }, () => {});
    release();
    await Promise.all([first.done, second.done]);
    expect(asked).toEqual(["one:0", "two:0"]);
  });

  it("passes the bridge's refusal on", async () => {
    const run = readAloud("x", () => Promise.reject({ code: "voice_no_provider", message: "No TTS provider available." }), () => {});
    await expect(run.done).rejects.toEqual({ code: "voice_no_provider", message: "No TTS provider available." });
  });
});
