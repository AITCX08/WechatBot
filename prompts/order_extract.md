你需要从用户消息中提取下单所需字段，输出一个严格的 JSON 对象。

字段定义：
- school: 学校名称 (string)
- user: 学号或账号 (string)
- password: 密码 (string)
- platform: 平台编号 (string, 通常是4位数字, 如 "1736")
- kcid: 课程 ID (string)
- kcname: 课程名称 (string)

输出格式（必须返回这个 JSON，不要任何额外文本）：
{
  "school": "<value or null>",
  "user": "<value or null>",
  "password": "<value or null>",
  "platform": "<value or null>",
  "kcid": "<value or null>",
  "kcname": "<value or null>",
  "missing": ["<list of missing field names>"]
}

历史对话上下文（按时间正序）：
{history}

最新一条消息："""{message}"""

请提取字段。无法判定的字段用 null，并在 missing 中列出所有 null 字段。
