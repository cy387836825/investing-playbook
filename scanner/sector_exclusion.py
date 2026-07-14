#!/usr/bin/env python3
"""行业与板块排除层(Sector & Industry Exclusion)——universe 之后、信号之前的最上游硬切。

在最上游直接切断高风险、非连续性经营的投机温床。规则用可得数据(Finviz sector/industry
+ EDGAR TTM营收/研发)近似 GICS/SIC 意图;不可得的子条款(借壳<3年、零售成功转型)诚实标注。

单旋钮:改此文件的常量即可调排除范围(对齐 assemble_viz.FLOOR_B 的一处可调模式)。
"""

# ==== 排除名单(strict/窄,用户 2026-07 拍板)====
SHELL = {'Shell Companies'}                                  # 空壳/SPAC(借壳<3年子条款数据不可得,未判)
BIOTECH_IND = 'Biotechnology'                                # 早期生物科技(需叠加零营收/研发占比条件)
BIOTECH_RND_RATIO = 0.80                                     # TTM研发/TTM营收 > 80% 视为无商业化产品
AIRLINE_MARINE = {'Airlines', 'Marine Shipping'}            # 航空与海运(重资产·无定价权·燃油周期)
COMMODITY_MICRO = {'Gold', 'Silver', 'Other Precious Metals & Mining', 'Coking Coal'}  # 二三线小资源商(叠加市值门槛)
COMMODITY_MCAP_CEIL = 2.0                                    # 市值 < $2B 才算"小"资源商
LEGACY_RETAIL_MEDIA = {'Broadcasting', 'Publishing',        # 衰退传统:媒体
                       'Department Stores', 'Apparel Retail'}  # + 实体零售(成功转型数据不可得)


def classify_exclusion(industry, mcap_b, ttm_rev=None, ttm_rnd=None):
    """判定一只票是否被"行业与板块排除"层剔除。

    只有 industry == Biotechnology 时才需要 ttm_rev/ttm_rnd(其余分支纯 industry+mcap);
    调用方据此只对生物科技票拉 EDGAR。

    返回 (excluded: bool, why: str)。未排除返回 (False, '')。
    """
    ind = (industry or '').strip()

    if ind in SHELL:
        return (True, '空壳/SPAC(Finviz行业=Shell Companies)—「借壳<3年」子条款需上市日期,免费数据不可得未判')

    if ind == BIOTECH_IND:
        rev = ttm_rev if (ttm_rev is not None and ttm_rev == ttm_rev) else None
        rnd = ttm_rnd if (ttm_rnd is not None and ttm_rnd == ttm_rnd) else None
        if rev is None or rev <= 0:
            return (True, '早期生物科技(零营收·无商业化产品)')
        if rnd is not None and rnd > BIOTECH_RND_RATIO * rev:
            r = round(100 * rnd / rev)
            return (True, f'早期生物科技(研发占营收{r}%>80%·无商业化产品)')
        return (False, '')

    if ind in AIRLINE_MARINE:
        return (True, f'航空/海运({ind})—重资产·无定价权·极度依赖燃油周期')

    if ind in COMMODITY_MICRO:
        mc = mcap_b if (mcap_b is not None and mcap_b == mcap_b) else None
        if mc is not None and mc < COMMODITY_MCAP_CEIL:
            return (True, f'二三线小资源商(市值${mc:.1f}B<$2B·{ind})')
        return (False, '')

    if ind in LEGACY_RETAIL_MEDIA:
        return (True, f'衰退传统行业({ind})—数字化结构性替代·「成功转型数据」不可得未评')

    return (False, '')


# ==== 网页展示用:该层的具体标准文案(供 funnel.json 内联 → index.html 点击展开)====
LAYER_CRITERIA = {
    'title': '行业与板块排除 · 硬编码切断高风险/非连续经营的投机温床(最上游)',
    'rules': [
        '空壳/SPAC:Finviz 行业 = Shell Companies 直接排除。⚠️「借壳上市未满3年」需 IPO/上市日期,免费数据不可得,未实现。',
        '早期生物科技:Finviz 行业 = Biotechnology 且(TTM营收 = 0,或 TTM研发/TTM营收 > 80%)—无商业化产品。',
        '航空与海运:行业 ∈ {Airlines, Marine Shipping}—重资产、无定价权、极度依赖燃油周期。',
        '商品小资源商:市值 < $2B 且行业 ∈ {Gold, Silver, 贵金属采矿, 焦煤}—二三线小资源勘探。',
        '衰退传统行业:行业 ∈ {Broadcasting, Publishing(媒体),Department Stores, Apparel Retail(实体零售)}。⚠️「无成功转型数据」需转型判定,未评估。',
    ],
    'note': '口径为 strict(窄):宁可少排、避免误杀优质龙头。GICS/SIC 无法从免费数据取得,以 Finviz sector/industry + EDGAR TTM 近似其意图。',
}
