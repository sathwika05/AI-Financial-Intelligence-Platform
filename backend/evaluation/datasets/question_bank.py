"""
Question specifications for the SQL-derived sets.

A specification is a question plus the query that answers it. It carries no
expected rows: those are read out of the database by
generate_ground_truth.py, because a reseed moves every fundamental and a
golden written by hand is stale the moment it is written.

  specification   question text, expected_sql, ordering contract   here
  ground truth    expected_sql_result, expected_ranking            derived

Diversity of shape, not permutation count. This session found four bugs and
each needed a structurally different question — the one that caught
`fm.market_cap` was the only one joining both tables, and no number of
extra top-K-by-metric variants would have found it. The builders below vary
the shape deliberately: queries that touch one table or two, filters that
eliminate almost everything, a K larger than the qualifying population,
columns that carry nulls, and sort keys that tie.

Every question is answerable against the seed. Where the seed cannot
support a shape, the question is narrowed rather than the ground truth
invented — a benchmark that asks for something absent measures nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Sectors with enough companies to rank. Consumer Defensive holds one
# company in the seed, so "the five largest" there is not a question.
RANKABLE_SECTORS = (
    "Technology",
    "Financial Services",
    "Healthcare",
    "Energy",
    "Industrials",
    "Consumer Cyclical",
    "Communication Services",
)

# Where each measure lives. The generator builds joins from this, so a
# query cannot reference fm.market_cap or c.eps — the two mistakes the SQL
# generator made in runs 4e10543d and 3a3ac0ed.
COMPANY_COLUMNS = frozenset({"market_cap", "sector", "ticker", "name"})
METRIC_COLUMNS = frozenset({"eps", "pe_ratio", "revenue_growth"})

# Measures where a zero or negative value makes a ranking meaningless, and
# the guard on the sort key is therefore `> 0` rather than a bare null
# check. This mirrors rule 3 of the SQL generator's own prompt — "if zero or
# negative values would make the ranking meaningless, exclude them" — so
# that a generator following its instructions produces the golden query
# rather than differing from it.
#
# revenue_growth and eps are deliberately absent. Both go negative in the
# seed and the negatives are meaningful: the weakest-growth questions exist
# to surface contraction, and filtering it out would answer a different
# question.
POSITIVE_ONLY_MEASURES = frozenset({"market_cap", "pe_ratio"})


@dataclass(frozen=True)
class QuestionSpec:
    """One question and the query that answers it, without its rows."""

    question_id: str
    question: str
    expected_sql: str
    expected_intent: str

    # See EvalQuestion.sql_order_requirement for the contract.
    sql_order_requirement: str = "top_k"

    expected_tools: tuple[str, ...] = ("planner", "sql")

    # Why this question exists, when it is not obvious. Carried into the
    # generated file so a reader knows what a failure here would mean.
    shape: str = ""

    # Set when the question is expected to return no rows or fewer than it
    # asks for. Those are legitimate questions, and the generator must not
    # treat an empty result as a mistake.
    allows_short_result: bool = field(default=False)


def _qualify(column: str) -> str:
    """Prefix a bare column with the alias of the table that owns it."""
    if column in COMPANY_COLUMNS:
        return f"c.{column}"

    if column in METRIC_COLUMNS:
        return f"fm.{column}"

    raise ValueError(
        f"Unknown column {column!r}. Add it to COMPANY_COLUMNS or "
        f"METRIC_COLUMNS so the join can be built correctly."
    )


def _needs_join(*columns: str) -> bool:
    return any(column in METRIC_COLUMNS for column in columns)


def build_sql(
    *,
    select: tuple[str, ...],
    order_by: str,
    direction: str,
    limit: int | None,
    sector: str | None = None,
    tickers: tuple[str, ...] = (),
    extra_where: tuple[str, ...] = (),
) -> str:
    """
    Assemble a SELECT from column names, joining only when needed.

    ticker and name are always projected: later stages match a row to a
    company by ticker, and a result without it cannot be matched at all.
    """
    columns = ("ticker", "name") + tuple(
        column
        for column in select
        if column not in {"ticker", "name"}
    )

    where: list[str] = []

    if sector:
        where.append(f"c.sector = '{sector}'")

    if tickers:
        joined = ", ".join(f"'{ticker}'" for ticker in tickers)
        where.append(f"c.ticker IN ({joined})")

    where.extend(extra_where)

    # A ranking over a column that is NULL for some rows would order them
    # arbitrarily, so the sort key is always constrained — unless a caller
    # already constrained it, since `> 0` implies NOT NULL and stating both
    # only makes the query noisier to read.
    sort_key = _qualify(order_by)

    if not any(clause.startswith(sort_key) for clause in extra_where):
        where.append(
            f"{sort_key} > 0"
            if order_by in POSITIVE_ONLY_MEASURES
            else f"{sort_key} IS NOT NULL"
        )

    # extra_where clauses arrive already qualified ("fm.eps > 0"), so the
    # prefix is the reliable signal there; projected and sorted columns are
    # bare names and go through the ownership map.
    join_needed = (
        _needs_join(*columns, order_by)
        or any("fm." in clause for clause in extra_where)
    )

    join = (
        " JOIN financial_metrics fm ON fm.company_id = c.id"
        if join_needed
        else ""
    )

    sql = (
        "SELECT "
        + ", ".join(_qualify(column) for column in columns)
        + " FROM companies c"
        + join
        + " WHERE "
        + " AND ".join(where)
        + f" ORDER BY {_qualify(order_by)} {direction}"
    )

    if limit is not None:
        sql += f" LIMIT {limit}"

    return sql


# ── Valuation ──────────────────────────────────────────────────────────
#
# Valuation asks how cheap or expensive a company is, and how large. The
# measures are pe_ratio and market_cap, with eps as the profitability
# filter. Every question naming a count is top_k: the sort decides which
# companies appear at all, so a bare LIMIT returns the wrong ones.

VALUATION_SPECS: list[QuestionSpec] = []


def _valuation() -> None:
    add = VALUATION_SPECS.append

    # 1-7. Cheapest by P/E, one per sector. One table plus the join;
    # pe_ratio carries nulls and negatives in the seed, so the filter is
    # doing real work.
    for index, sector in enumerate(RANKABLE_SECTORS, start=1):
        add(QuestionSpec(
            question_id=f"valuation_pe_sector_{index:02d}",
            question=(
                f"Which three {sector} companies have the lowest P/E "
                f"ratios? Rank them from lowest to highest."
            ),
            expected_sql=build_sql(
                select=("pe_ratio",),
                order_by="pe_ratio",
                direction="ASC",
                limit=3,
                sector=sector,
                extra_where=("fm.pe_ratio > 0",),
            ),
            expected_intent="VALUATION",
            shape="single metric, sector-scoped, positive filter",
        ))

    # 8-14. Largest by market cap, one per sector. Deliberately no join:
    # market_cap lives on companies, and a generator that reaches for
    # financial_metrics here has misunderstood the schema.
    for index, sector in enumerate(RANKABLE_SECTORS, start=8):
        add(QuestionSpec(
            question_id=f"valuation_cap_sector_{index:02d}",
            question=(
                f"Rank the three largest {sector} companies by market "
                f"capitalization, from largest to smallest."
            ),
            expected_sql=build_sql(
                select=("market_cap",),
                order_by="market_cap",
                direction="DESC",
                limit=3,
                sector=sector,
            ),
            expected_intent="VALUATION",
            shape="no join required — market_cap is on companies",
        ))

    # 15-18. Profitability filter across both tables. This is the shape
    # that caught the schema-split bugs: the filter column and the sort
    # column live on different tables.
    for index, (sector, count) in enumerate(
        (
            ("Technology", 5),
            ("Healthcare", 5),
            ("Financial Services", 5),
            ("Industrials", 3),
        ),
        start=15,
    ):
        add(QuestionSpec(
            question_id=f"valuation_profitable_{index:02d}",
            question=(
                f"Which {count} profitable {sector} companies have the "
                f"smallest market capitalizations? Rank them from smallest "
                f"to largest market cap."
            ),
            expected_sql=build_sql(
                select=("market_cap",),
                order_by="market_cap",
                direction="ASC",
                limit=count,
                sector=sector,
                extra_where=("fm.eps > 0",),
            ),
            expected_intent="VALUATION",
            shape="filter and sort on different tables",
        ))

    # 19-22. Most expensive by P/E. Reverses the direction so a generator
    # that hardcodes ASC for anything P/E-shaped is caught.
    for index, sector in enumerate(
        ("Technology", "Healthcare", "Consumer Cyclical", "Energy"),
        start=19,
    ):
        add(QuestionSpec(
            question_id=f"valuation_expensive_{index:02d}",
            question=(
                f"Which three {sector} companies are the most expensive by "
                f"P/E ratio? Rank them from highest to lowest."
            ),
            expected_sql=build_sql(
                select=("pe_ratio",),
                order_by="pe_ratio",
                direction="DESC",
                limit=3,
                sector=sector,
                extra_where=("fm.pe_ratio > 0",),
            ),
            expected_intent="VALUATION",
            shape="descending — direction must follow the wording",
        ))

    # 23-25. K larger than the qualifying population. A correct answer
    # returns everything that qualifies; padding the result to reach the
    # requested count is wrong.
    for index, sector in enumerate(
        ("Communication Services", "Energy", "Industrials"),
        start=23,
    ):
        add(QuestionSpec(
            question_id=f"valuation_short_{index:02d}",
            question=(
                f"List the ten {sector} companies with the lowest P/E "
                f"ratios, ranked from lowest to highest."
            ),
            expected_sql=build_sql(
                select=("pe_ratio",),
                order_by="pe_ratio",
                direction="ASC",
                limit=10,
                sector=sector,
                extra_where=("fm.pe_ratio > 0",),
            ),
            expected_intent="VALUATION",
            shape="K exceeds the population — a short result is correct",
            allows_short_result=True,
        ))

    # 26-28. Unscoped across all sectors, varying K, so LIMIT handling is
    # tested independently of the sector filter.
    for index, count in enumerate((3, 5, 10), start=26):
        add(QuestionSpec(
            question_id=f"valuation_market_{index:02d}",
            question=(
                f"Across all sectors, which {count} companies have the "
                f"lowest P/E ratios? Rank them from lowest to highest."
            ),
            expected_sql=build_sql(
                select=("pe_ratio",),
                order_by="pe_ratio",
                direction="ASC",
                limit=count,
                extra_where=("fm.pe_ratio > 0",),
            ),
            expected_intent="VALUATION",
            shape="no sector filter, varying K",
        ))

    # 29. Two conditions on two different metric columns.
    add(QuestionSpec(
        question_id="valuation_compound_29",
        question=(
            "Which five profitable companies trade below a P/E ratio of "
            "25? Rank them from lowest to highest P/E."
        ),
        expected_sql=build_sql(
            select=("pe_ratio", "eps"),
            order_by="pe_ratio",
            direction="ASC",
            limit=5,
            extra_where=("fm.eps > 0", "fm.pe_ratio > 0", "fm.pe_ratio < 25"),
        ),
        expected_intent="VALUATION",
        shape="compound filter, two metric columns projected",
    ))

    # 30. A ranking with no count. The question orders a population rather
    # than selecting from it, so membership is not at stake and the
    # contract is "ranking" rather than "top_k".
    add(QuestionSpec(
        question_id="valuation_ranking_30",
        question=(
            "Rank every Energy company by market capitalization, from "
            "largest to smallest."
        ),
        expected_sql=build_sql(
            select=("market_cap",),
            order_by="market_cap",
            direction="DESC",
            limit=None,
            sector="Energy",
        ),
        expected_intent="VALUATION",
        sql_order_requirement="ranking",
        shape="no LIMIT — ordering without selection",
    ))


_valuation()


# ── Growth ─────────────────────────────────────────────────────────────
#
# Growth ranks on revenue_growth. The seed has no eps_growth column, so a
# question asking for earnings growth would penalise the pipeline for not
# returning a figure the database cannot produce — every question here
# ranks on revenue growth, and the ones that mention profitability use eps
# as a filter rather than as the ranking key.

GROWTH_SPECS: list[QuestionSpec] = []


def _growth() -> None:
    add = GROWTH_SPECS.append

    # 1-7. Fastest growing, one per sector.
    for index, sector in enumerate(RANKABLE_SECTORS, start=1):
        add(QuestionSpec(
            question_id=f"growth_sector_{index:02d}",
            question=(
                f"Rank the three {sector} companies with the strongest "
                f"revenue growth, from highest to lowest."
            ),
            expected_sql=build_sql(
                select=("revenue_growth",),
                order_by="revenue_growth",
                direction="DESC",
                limit=3,
                sector=sector,
            ),
            expected_intent="GROWTH",
            shape="sector-scoped growth ranking",
        ))

    # 8-14. Slowest growing. revenue_growth goes negative in the seed, so
    # ascending order surfaces contraction — a filter excluding negatives
    # here would answer a different question and is deliberately absent.
    for index, sector in enumerate(RANKABLE_SECTORS, start=8):
        add(QuestionSpec(
            question_id=f"growth_slowest_{index:02d}",
            question=(
                f"Which three {sector} companies have the weakest revenue "
                f"growth? Rank them from weakest to strongest."
            ),
            expected_sql=build_sql(
                select=("revenue_growth",),
                order_by="revenue_growth",
                direction="ASC",
                limit=3,
                sector=sector,
            ),
            expected_intent="GROWTH",
            shape="ascending — negatives must NOT be filtered out",
        ))

    # 15-18. Growth with a profitability filter. Filter and sort are both
    # on financial_metrics here, which is the easier of the two join
    # shapes and worth having alongside the harder one.
    for index, (sector, count) in enumerate(
        (
            ("Technology", 3),
            ("Healthcare", 3),
            ("Financial Services", 5),
            ("Consumer Cyclical", 3),
        ),
        start=15,
    ):
        add(QuestionSpec(
            question_id=f"growth_profitable_{index:02d}",
            question=(
                f"Among profitable {sector} companies, which {count} have "
                f"the strongest revenue growth? Rank them from highest to "
                f"lowest."
            ),
            expected_sql=build_sql(
                select=("revenue_growth", "eps"),
                order_by="revenue_growth",
                direction="DESC",
                limit=count,
                sector=sector,
                extra_where=("fm.eps > 0",),
            ),
            expected_intent="GROWTH",
            shape="filter and sort both on financial_metrics",
        ))

    # 19-22. Growth among large companies. Filter on companies, sort on
    # financial_metrics — the reverse of the valuation case, so a
    # generator cannot pass by assuming one table owns filters.
    for index, (sector, floor) in enumerate(
        (
            ("Technology", 500_000_000_000),
            ("Healthcare", 100_000_000_000),
            ("Financial Services", 100_000_000_000),
            ("Energy", 50_000_000_000),
        ),
        start=19,
    ):
        add(QuestionSpec(
            question_id=f"growth_large_{index:02d}",
            question=(
                f"Among {sector} companies with a market capitalization "
                f"above ${floor // 1_000_000_000} billion, which three "
                f"have the strongest revenue growth? Rank them from "
                f"highest to lowest."
            ),
            expected_sql=build_sql(
                select=("revenue_growth", "market_cap"),
                order_by="revenue_growth",
                direction="DESC",
                limit=3,
                sector=sector,
                extra_where=(f"c.market_cap > {floor}",),
            ),
            expected_intent="GROWTH",
            shape="filter on companies, sort on financial_metrics",
            allows_short_result=True,
        ))

    # 23-25. Unscoped, varying K.
    for index, count in enumerate((3, 5, 10), start=23):
        add(QuestionSpec(
            question_id=f"growth_market_{index:02d}",
            question=(
                f"Rank the {count} companies with the strongest revenue "
                f"growth based on the latest available financial metrics."
            ),
            expected_sql=build_sql(
                select=("revenue_growth",),
                order_by="revenue_growth",
                direction="DESC",
                limit=count,
            ),
            expected_intent="GROWTH",
            shape="unscoped, varying K",
        ))

    # 26-28. Growth above a threshold. The filter and the sort key are the
    # same column, which is a shape that invites dropping one of them.
    for index, threshold in enumerate((0.20, 0.30, 0.50), start=26):
        add(QuestionSpec(
            question_id=f"growth_threshold_{index:02d}",
            question=(
                f"Which companies grew revenue by more than "
                f"{int(threshold * 100)}%? Rank them from highest growth "
                f"to lowest."
            ),
            expected_sql=build_sql(
                select=("revenue_growth",),
                order_by="revenue_growth",
                direction="DESC",
                limit=None,
                extra_where=(f"fm.revenue_growth > {threshold}",),
            ),
            expected_intent="GROWTH",
            sql_order_requirement="ranking",
            shape="threshold on the sort column, no LIMIT",
        ))

    # 29. Contraction. A question whose honest answer may be a short list.
    add(QuestionSpec(
        question_id="growth_contraction_29",
        question=(
            "Which companies had negative revenue growth? Rank them from "
            "the steepest decline upward."
        ),
        expected_sql=build_sql(
            select=("revenue_growth",),
            order_by="revenue_growth",
            direction="ASC",
            limit=None,
            extra_where=("fm.revenue_growth < 0",),
        ),
        expected_intent="GROWTH",
        sql_order_requirement="ranking",
        shape="negative filter — result may be small or empty",
        allows_short_result=True,
    ))

    # 30. Growth and valuation together: cheap and growing.
    add(QuestionSpec(
        question_id="growth_cheap_30",
        question=(
            "Which five companies combine revenue growth above 10% with a "
            "P/E ratio below 30? Rank them from highest growth to lowest."
        ),
        expected_sql=build_sql(
            select=("revenue_growth", "pe_ratio"),
            order_by="revenue_growth",
            direction="DESC",
            limit=5,
            extra_where=(
                "fm.revenue_growth > 0.10",
                "fm.pe_ratio > 0",
                "fm.pe_ratio < 30",
            ),
        ),
        expected_intent="GROWTH",
        shape="two metrics constrained, one of them the sort key",
    ))


_growth()


SPEC_SETS: dict[str, list[QuestionSpec]] = {
    "valuation": VALUATION_SPECS,
    "growth": GROWTH_SPECS,
}
