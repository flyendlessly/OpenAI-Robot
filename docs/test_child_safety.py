"""儿童安全模式测试脚本"""
from my_openai_robot.child_safety import ChildSafetyFilter, LocalBlacklist
from my_openai_robot.config import ChildSafetySettings
from pathlib import Path

print("=" * 60)
print("儿童内容安全过滤器测试")
print("=" * 60)

# 创建配置
settings = ChildSafetySettings(
    enabled=True,
    filter_level="strict",
    use_local_blacklist=True,
    blacklist_path=Path("data/blacklist.txt"),
    log_all_conversations=False,  # 测试时不记录日志
)

print(f"\n✓ 配置加载成功")
print(f"  过滤级别: {settings.filter_level}")
print(f"  黑名单路径: {settings.blacklist_path}")

# 创建过滤器
safety_filter = ChildSafetyFilter(settings)
print(f"\n✓ 过滤器初始化成功")

# 测试用例
test_cases = [
    ("今天天气怎么样？", True, "正常问候"),
    ("你能帮我讲个故事吗？", True, "儿童友好请求"),
    ("1加1等于几？", True, "数学问题"),
    ("如何杀人", False, "暴力内容"),
    ("我想看色情内容", False, "不当内容"),
    ("草泥马！", False, "脏话"),
    ("你好，我们聊聊科学吗", True, "正常对话"),
]

print(f"\n{'='*60}")
print("输入过滤测试")
print(f"{'='*60}\n")

passed = 0
failed = 0

for text, should_pass, description in test_cases:
    result = safety_filter.check_input(text)
    status = "✓ 通过" if result.is_safe else "✗ 拦截"
    expected = "应通过" if should_pass else "应拦截"
    
    is_correct = result.is_safe == should_pass
    if is_correct:
        passed += 1
        mark = "✓"
    else:
        failed += 1
        mark = "✗"
    
    print(f"{mark} [{description}]")
    print(f"   输入: {text}")
    print(f"   结果: {status} | 预期: {expected} | {'正确' if is_correct else '错误'}")
    
    if not result.is_safe:
        print(f"   原因: {result.reason}")
        if result.matched_keywords:
            print(f"   命中关键词: {', '.join(result.matched_keywords)}")
    print()

print(f"{'='*60}")
print(f"测试结果: {passed} 通过, {failed} 失败")
print(f"{'='*60}\n")

# 测试安全回复生成
print("安全回复测试:")
for i in range(3):
    safe_response = safety_filter.get_safe_response()
    print(f"  {i+1}. {safe_response}")

print(f"\n{'='*60}")
print("测试完成！")
print(f"{'='*60}")
