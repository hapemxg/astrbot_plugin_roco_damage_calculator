import random
import re
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# --- 核心计算逻辑 ---

def calculate_modifier(level: int) -> float:
    """
    根据强化/弱化等级计算能力值的修正系数。
    - 正数等级表示强化，负数表示弱化。
    - 公式: 强化: (2 + 等级) / 2, 弱化: 2 / (2 + |等级|)
    """
    if level > 0:
        return (2 + level) / 2
    elif level < 0:
        return 2 / (2 + abs(level))
    else:
        return 1.0

def calculate_damage(power: int, attack: int, defense: int, attack_level: int, defense_level: int, type_multiplier: float) -> tuple[int, int, int]:
    """
    根据洛克王国伤害公式计算最终伤害。
    - 包含等级、威力、攻防、强化、属性克制和随机数修正。
    """
    pet_level = 100
    modified_attack = attack * calculate_modifier(attack_level)
    modified_defense = max(1, defense * calculate_modifier(defense_level))
    base_damage = ((((pet_level * 2 / 5 + 2) * power * (modified_attack / modified_defense)) / 50) + 2)
    modified_base_damage = base_damage * type_multiplier
    min_damage = int(modified_base_damage * 0.80)
    max_damage = int(modified_base_damage)
    current_damage = random.randint(min_damage, max_damage) if min_damage < max_damage else min_damage
    return min_damage, max_damage, current_damage

# --- AstrBot 插件定义 ---

@register(
    "DamageCalculator",
    "Roco",
    "一个用于计算《洛克王国页游》威力伤害的插件",
    "1.0"  
)
class DamageCalculatorPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("伤害计算")
    async def damage_command_final(self, event: AstrMessageEvent):
        """
        洛克王国伤害计算器主指令。
        支持基础能力、强化等级、属性相性和战斗内加成。
        """
        text = event.message_str

        # --- 1. 未知参数校验 ---
        VALID_KEYWORDS = {
            "威力", "攻击", "防御", "攻击强化", "防御强化",
            "双重克制", "双克", "克制", "强力抵抗", "双重抵抗", "抵抗",
            "面板", "面板能力值", "帮助"
        }
        args_text = text.replace("伤害计算", "", 1).strip()
        input_parts = re.split(r'\s+', args_text) if args_text else []
        unknown_params = []
        for part in input_parts:
            match = re.match(r'([一-龥]+)', part)
            if match and match.group(1) not in VALID_KEYWORDS:
                unknown_params.append(match.group(1))
        if unknown_params:
            unique_unknowns = sorted(list(set(unknown_params)))
            yield event.plain_result(f"错误：检测到未知参数 -> {', '.join(unique_unknowns)}\n请发送 /伤害计算帮助 查看可用参数。")
            return

        # --- 2. 指令处理与参数提取 ---
        if "帮助" in text:
            yield event.plain_result("需要查看帮助说明吗？请发送：\n/伤害计算帮助")
            return

        pattern = r"(威力|攻击|防御|攻击强化|防御强化)(-?\d+)"
        matches = re.findall(pattern, text)
        params = {key: int(value) for key, value in matches}
        original_attack = params.get("攻击")
        original_defense = params.get("防御")
        attack_level = params.get("攻击强化", 0)
        defense_level = params.get("防御强化", 0)
        if original_attack is None or original_defense is None or params.get("威力") is None:
            yield event.plain_result("参数不足或格式错误，请发送 /伤害计算帮助 查看详细说明。")
            return

        # --- 3. 战斗内加成处理 ---
        attack_for_calc = original_attack
        defense_for_calc = original_defense
        panel_bonus_applied = any(kw in text for kw in ["面板", "面板能力值"])
        if panel_bonus_applied:
            attack_for_calc += 140
            defense_for_calc += 140

        # --- 4. 属性相性处理 ---
        type_categories = [
            any(kw in text for kw in ["双重克制", "双克"]),
            any(kw in text for kw in ["克制"]) and not any(kw in text for kw in ["双重克制"]),
            any(kw in text for kw in ["强力抵抗", "双重抵抗"]),
            any(kw in text for kw in ["抵抗"]) and not any(kw in text for kw in ["强力抵抗", "双重抵抗"])
        ]
        if sum(type_categories) > 1:
            yield event.plain_result("属性相性参数冲突！一次只能使用一种关系。\n请发送 /伤害计算帮助 查看详细说明。")
            return
        type_multiplier = 1.0
        type_effectiveness_str = "无"
        if "双重克制" in text or "双克" in text:
            type_multiplier, type_effectiveness_str = 3.0, "双重克制 (x3.0)"
        elif "克制" in text:
            type_multiplier, type_effectiveness_str = 2.0, "克制 (x2.0)"
        elif "强力抵抗" in text or "双重抵抗" in text:
            type_multiplier, type_effectiveness_str = 1/3, f"强力抵抗 (x{1/3:.2f})"
        elif "抵抗" in text:
            type_multiplier, type_effectiveness_str = 0.5, "抵抗 (x0.5)"

        # --- 5. 数据校验与计算 ---
        if not (-6 <= attack_level <= 6 and -6 <= defense_level <= 6):
            yield event.plain_result("错误：强化等级必须在 -6 到 6 之间。")
            return
        min_dmg, max_dmg, current_dmg = calculate_damage(
            params["威力"], attack_for_calc, defense_for_calc,
            attack_level, defense_level, type_multiplier
        )

        # --- 6. 构建并发送结果 ---
        # 根据是否使用了'面板'参数，动态构建回复消息。
        if panel_bonus_applied:
            # 详细模式：当使用'面板'参数时，同时显示背包和战斗能力值。
            reply_message = (
                f"伤害计算结果：\n"
                f"-------------------\n"
                f"攻击方信息：\n"
                f"  - 面板攻击能力值: {original_attack}\n"
                f"  - 实际攻击能力值: {attack_for_calc} (强化等级: {attack_level})\n"
                f"受击方信息：\n"
                f"  - 面板防御能力值: {original_defense}\n"
                f"  - 实际防御能力值: {defense_for_calc} (强化等级: {defense_level})\n"
                f"技能威力: {params['威力']}\n"
                f"属性相性: {type_effectiveness_str}\n"
                f"-------------------\n"
                f"本次随机伤害: {current_dmg}\n"
                f"伤害浮动范围: {min_dmg} ~ {max_dmg}"
            )
        else:
            # 简洁模式：当不使用'面板'参数时，只显示最终用于计算的能力值。
            reply_message = (
                f"伤害计算结果：\n"
                f"-------------------\n"
                f"攻击方信息：\n"
                f"  - 攻击: {attack_for_calc} (强化等级: {attack_level})\n"
                f"受击方信息：\n"
                f"  - 防御: {defense_for_calc} (强化等级: {defense_level})\n"
                f"技能威力: {params['威力']}\n"
                f"属性相性: {type_effectiveness_str}\n"
                f"-------------------\n"
                f"本次随机伤害: {current_dmg}\n"
                f"伤害浮动范围: {min_dmg} ~ {max_dmg}"
            )

        yield event.plain_result(reply_message)

    @filter.command("伤害计算帮助")
    async def damage_command_help(self, event: AstrMessageEvent):
        """
        显示伤害计算器的详细使用说明和示例。
        """
        help_text = (
            "--- 洛克王国页游伤害计算器帮助 ---\n\n"
            "指令格式 (参数顺序可随意打乱):\n"
            "/伤害计算 威力<数值> 攻击<数值> 防御<数值>\n\n"
            "--- 可选参数 ---\n\n"
            "1. 强化等级 (范围: -6 到 6):\n"
            "   - `攻击强化<等级>`\n"
            "   - `防御强化<等级>`\n\n"
            "2. 属性相性 (一次只能用一个):\n"
            "   - `克制` (伤害 x2.0)\n"
            "   - `抵抗` (伤害 x0.5)\n"
            "   - `双克` / `双重克制` (伤害 x3.0)\n"
            "   - `强力抵抗` / `双重抵抗` (伤害 x0.33)\n\n"
            "3. 战斗内加成 (模拟装备和守护兽):\n"
            "   - `面板` 或 `面板能力值`\n"
            "   - 说明: 使用此参数时，输入的【攻击】和【防御】应为宠物背包中看到的基础值。计算器会自动为其增加140点 (90装备 + 50守护兽) 来模拟战斗中的实际能力值。\n\n"
            "--- 示例 ---\n\n"
            "▶︎ 基础计算 (输入战斗内的实际能力值):\n"
            "/伤害计算 威力120 攻击490 防御340\n\n"
            "▶︎ 复杂计算 (输入背包能力值，并使用面板加成):\n"
            "/伤害计算 威力90 攻击400 防御300 攻击强化2 防御强化-1 克制 面板"
        )
        yield event.plain_result(help_text)

