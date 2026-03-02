# 儿童内容安全保护配置示例

本项目为儿童用户提供**企业级三层防护**，确保对话内容健康、安全。

## 快速启用

在 `.env` 文件中设置：

```env
CHILD_MODE=true
CONTENT_FILTER_LEVEL=strict
```

## 三层防护架构

### 第 1 层：本地关键词黑名单（输入预过滤）
- **位置**: `data/blacklist.txt`
- **作用**: 快速拦截明显违规输入，避免浪费 API 调用
- **响应速度**: < 1ms
- **可自定义**: 是，可编辑 `blacklist.txt` 添加/删除关键词

### 第 2 层：System Prompt 引导（AI 行为约束）
- **作用**: 通过系统提示词引导 AI 使用儿童友好语言
- **自定义**: 通过 `CHILD_SYSTEM_prompt` 环境变量配置

### 第 3 层：Azure 内容过滤器（输出后审查）
- **作用**: AI 回复后再次检查，拦截潜在不当内容
- **技术**: 微软官方多语言过滤模型
- **分类**: 暴力、性、仇恨、自残 4 大类，0-6 级评分

## 配置说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `CHILD_MODE` | `false` | 启用儿童安全模式 |
| `CONTENT_FILTER_LEVEL` | `strict` | 过滤级别：low/medium/strict |
| `USE_LOCAL_BLACKLIST` | `true` | 启用本地黑名单预过滤 |
| `BLACKLIST_PATH` | `data/blacklist.txt` | 黑名单文件路径 |
| `LOG_ALL_CONVERSATIONS` | `true` | 记录所有对话供家长审查 |
| `CONVERSATION_LOG_PATH` | `data/conversation_logs` | 对话日志目录 |

## 过滤级别对比

| 级别 | 拦截阈值 | 适用场景 | 误拦截率 |
|-----|---------|---------|---------|
| `low` | ≥ 6 级 | 青少年（13+） | 低 |
| `medium` | ≥ 4 级 | 少儿（9-12 岁） | 中 |
| `strict` | ≥ 2 级 | 幼儿（6-8 岁）| 较高（推荐） |

## 对话日志格式

日志以 JSONL 格式存储在 `data/conversation_logs/YYYY-MM-DD.jsonl`：

```json
{
  "timestamp": "2026-03-02T14:30:15.123456",
  "user_input": "今天天气怎么样？",
  "assistant_response": "今天天气很好哦！阳光明媚，适合出去玩。",
  "filter_results": [
    {"is_safe": true, "reason": "", "layer": "local_blacklist"},
    {"is_safe": true, "reason": "", "layer": "output_check"}
  ],
  "metadata": {"blocked": false}
}
```

## 家长审查

查看对话记录：

```bash
# 查看今天的对话
cat data/conversation_logs/2026-03-02.jsonl | jq .

# 查看被拦截的对话
cat data/conversation_logs/*.jsonl | jq 'select(.metadata.blocked == true)'

# 统计每日对话数量
cat data/conversation_logs/*.jsonl | wc -l
```

## 自定义黑名单

编辑 `data/blacklist.txt`：

```
# 基本关键词
暴力
血腥

# 支持正则表达式（用 / 包裹）
/sha.*ren/
/cao.*ni.*ma/

# 注释以 # 开头
```

## 测试

```bash
# 启用儿童模式测试
CHILD_MODE=true python -m my_openai_robot --voice-turn --use-vad

# 查看配置状态
python -m my_openai_robot --voice-turn --use-vad
# 输出会显示：
# 🧒 儿童安全模式已启用
#    过滤级别: strict
#    本地黑名单: ✓
#    Azure 过滤: ✓
#    对话日志: ✓
```

## 注意事项

1. **误拦截**: strict 模式可能拦截正常词汇（如"杀毒软件"），可降级为 medium
2. **性能**: 本地黑名单检查几乎无延迟，不影响体验
3. **隐私**: 对话日志存储本地，不上传云端
4. **更新**: 定期根据日志更新 `blacklist.txt`

## 禁用方法

在 `.env` 中设置：

```env
CHILD_MODE=false
```

或删除该配置项（默认禁用）。
