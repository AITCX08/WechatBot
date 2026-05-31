"""真机接收链路探针：连已在跑的 sidecar /stream，抓前 N 条真实 SSE 帧打印原文。

用途（真机测试第 1 步）：核对 wx/receive.py 的字段解析是否匹配 sidecar 真实输出。
不依赖 bot / dashboard，只读 SSE。

前置：sidecar 已在 http://127.0.0.1:5678 跑起来且微信已登录。
用法：python scripts/probe_sse.py [URL] [N]
    URL 默认 http://127.0.0.1:5678/stream
    N   默认 8（抓够 N 条 data 帧就退出）
"""
import sys
import json
import requests

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5678/stream"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 8


def main():
    print(f"[probe] connecting {URL} ; will capture {N} data frames")
    print("[probe] 现在去微信里给「文件传输助手」发一条文本，或让别人给你发消息……\n")
    got = 0
    cur_event = None
    try:
        with requests.get(URL, stream=True, timeout=(5, None)) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                line = raw.strip("\r")
                if line == "":
                    cur_event = None
                    continue
                if line.startswith(":"):
                    print(f"[heartbeat] {line!r}")
                    continue
                if line.startswith("event:"):
                    cur_event = line[len("event:"):].strip()
                    print(f"[event-line] event={cur_event}")
                    continue
                if line.startswith("data:"):
                    body = line[len("data:"):].strip()
                    tag = f"(event={cur_event})" if cur_event else "(bare data frame)"
                    print(f"\n===== DATA FRAME #{got+1} {tag} =====")
                    try:
                        obj = json.loads(body)
                        print(json.dumps(obj, ensure_ascii=False, indent=2))
                        print("KEYS:", sorted(obj.keys()))
                    except Exception as e:
                        print("RAW (not json):", body[:500], "| err:", e)
                    got += 1
                    if got >= N:
                        print(f"\n[probe] captured {N} frames, done.")
                        return
                else:
                    print(f"[other-line] {line!r}")
    except KeyboardInterrupt:
        print("\n[probe] interrupted.")
    except Exception as e:
        print(f"[probe] ERROR: {e}")


if __name__ == "__main__":
    main()
