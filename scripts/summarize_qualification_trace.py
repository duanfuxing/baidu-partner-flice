"""从脱敏采集文件生成请求索引、动作时间线和上传/保存关联。"""

import argparse
from collections import Counter
import json
from pathlib import Path


def summarize(directory):
    directory = Path(directory)
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    requests = {}
    for event in events:
        rid = event.get('request_id')
        if event['kind'] == 'request':
            requests[rid] = dict(event)
        elif rid in requests:
            row = requests[rid]
            if event['kind'] == 'response':
                row['http_status'] = event['status']
            elif event['kind'] == 'finished':
                row['duration_ms'] = event['duration_ms']
            elif event['kind'] == 'response_body':
                row['response_body'] = event['body']
            elif event['kind'] == 'failed':
                row['failure'] = event['reason']
    rows = list(requests.values())
    (directory/'request-index.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    counts = Counter((r['method'], r['url']['host'], r['url']['path']) for r in rows)
    lines = ['# 单资质网络采集报告', '',
             f'事件数：{len(events)}；浏览器请求数：{len(rows)}。', '',
             '本报告由脱敏事件生成。phase 是收到事件时程序所处阶段，不单独证明因果；CDP 调用栈可辅助判断发起来源。',
             '请求值使用本次采集内一致的匿名标识；同一文件上传返回值、预览 filename 与保存 upload_file 可关联。', '',
             '## 完成证据', '']
    verified = [e for e in events if e['kind'] == 'verification']
    lines.append('已重新打开详情，文件内容和举证链接验证通过。' if verified else '尚无重新打开后的完整验证成功记录，不能认定资质已完成。')
    lines.extend(['', '## 接口与资源请求统计', '', '| 方法 | 主机 | 路径（动态路径已脱敏） | 次数 |', '| --- | --- | --- | --- |'])
    for (method, host, path), count in counts.most_common():
        lines.append(f'| {method} | {host} | {path} | {count} |')
    lines.extend(['', '## 动作时间线', '', '| 秒 | 动作 |', '| --- | --- |'])
    for e in events:
        if e['kind'] == 'action':
            lines.append(f"| {e['elapsed_ms']/1000:.3f} | {e['name']} |")
    lines.extend(['', '## XHR / fetch 请求时间线', '',
                  '| 秒 | 请求 | 接口 | HTTP | 业务状态 | 耗时 ms | 阶段 |', '| --- | --- | --- | --- | --- | --- | --- |'])
    for r in rows:
        if r['resource_type'] not in ('xhr', 'fetch'):
            continue
        body = r.get('response_body')
        status = body.get('status', body.get('code', '')) if isinstance(body, dict) else ''
        lines.append(f"| {r['elapsed_ms']/1000:.3f} | {r['request_id']} | {r['url']['path']} | {r.get('http_status', r.get('failure', 'pending'))} | {status} | {r.get('duration_ms', '')} | {r['phase']} |")
    lines.extend(['', '## 上传与保存的文件关联', ''])
    for r in rows:
        path = r['url']['path']
        if path.endswith('/savelicepic'):
            lines.append(f"- {r['request_id']} 上传响应：`{json.dumps(r.get('response_body'), ensure_ascii=False)}`")
        elif path.endswith('/submitlice'):
            body = r.get('body') or {}
            files = body.get('upload_file') if isinstance(body, dict) else None
            lines.append(f"- {r['request_id']} 保存关联文件：`{json.dumps(files, ensure_ascii=False)}`；HTTP {r.get('http_status')}。")
    lines.extend(['', '## 采集限制', '',
                  '- 登录过程不采集；工作流通过 APIRequestContext 发出的公司查询不属于浏览器网络事件。资质详情打开后的浏览器请求持续采集。',
                  '- 路由保护会禁用 HTTP 缓存，时延不能直接代表普通用户环境。',
                  '- 页面状态按 250 ms 采样并记录变化；短于此间隔的临时状态可能遗漏。',
                  '- 程序主动读取预览内容也会产生请求，应结合标记和调用栈与页面原生请求区分。',
                  '- 请求头、文件二进制、非 JSON 响应体不落盘；WebSocket 仅记录连接，未记录帧内容。',
                  '- multipart 中捕获的文件字节可能被 Chromium 省略；旧记录 bytes=0 不代表源文件为空，源文件大小和哈希以 capture_config/verification 为准。',
                  '- 缺少故障现场时不能从单次成功样本推断所有失败根因。'])
    (directory/'timeline.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return {'events': len(events), 'requests': len(rows), 'persisted_verified': bool(verified)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), ensure_ascii=False))
