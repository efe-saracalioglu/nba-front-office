from datetime import date

from data.sources.bbref import parse_advanced, parse_contracts


def _adv_row(slug, name, team, g, ws, usg, usg_csk=True):
    usg_attr = f' csk="{usg / 100}"' if usg_csk else ""
    return f"""<tr><th data-stat="ranker">1</th>
      <td data-append-csv="{slug}" data-stat="name_display"><a>{name}</a></td>
      <td data-stat="age">25</td><td data-stat="team_name_abbr">{team}</td>
      <td data-stat="pos">C</td><td data-stat="games">{g}</td>
      <td data-stat="games_started">{g}</td><td data-stat="mp">{g * 30}</td>
      <td data-stat="ts_pct" csk="0.6123">.612</td>
      <td data-stat="usg_pct"{usg_attr}>{usg}</td>
      <td data-stat="ws" csk="{ws}">{round(ws, 1)}</td></tr>"""


ADVANCED_HTML = f"""<html><body><table id="advanced"><thead><tr><th>x</th></tr></thead><tbody>
{_adv_row("traded01", "Traded Guy", "2TM", 60, 6.25, 24.0)}
{_adv_row("traded01", "Traded Guy", "DAL", 30, 3.0, 24.0)}
{_adv_row("traded01", "Traded Guy", "LAL", 30, 3.25, 24.0)}
<tr class="thead"><th>Rk</th></tr>
{_adv_row("oldpage01", "Old Page", "BOS", 70, 4.0, 18.5, usg_csk=False)}
<tr><td data-stat="name_display">League Average</td></tr>
</tbody></table></body></html>"""


def test_advanced_keeps_combined_row_for_traded_players():
    df = parse_advanced(ADVANCED_HTML, "2024-25").set_index("bbref_id")
    assert list(df.index) == ["traded01", "oldpage01"]
    assert df.loc["traded01", "g"] == 60
    assert df.loc["traded01", "ws"] == 6.25
    assert df.loc["traded01", "season"] == "2024-25"


def test_advanced_percentages_are_fractions_with_or_without_csk():
    df = parse_advanced(ADVANCED_HTML, "2024-25").set_index("bbref_id")
    assert df.loc["traded01", "usg_pct"] == 0.24
    assert abs(df.loc["oldpage01", "usg_pct"] - 0.185) < 1e-9
    assert df.loc["oldpage01", "ts_pct"] == 0.6123


CONTRACTS_HTML = """<table id="player-contracts"><thead><tr>
<th data-stat="ranker">Rk</th><th data-stat="player">Player</th><th data-stat="team_id">Tm</th>
<th data-stat="y1">2026-27</th><th data-stat="y2">2027-28</th><th data-stat="y3">2028-29</th>
</tr></thead><tbody>
<tr><th data-stat="ranker">1</th><td data-append-csv="star01" data-stat="player"><a>Star</a></td>
<td data-stat="team_id">PHO</td>
<td data-stat="y1" csk="50000000">$50,000,000</td>
<td class="right salary-pl" data-stat="y2" csk="52000000">$52,000,000</td>
<td class="right iz" data-stat="y3"></td></tr>
<tr><th data-stat="ranker">2</th><td data-append-csv="waived01" data-stat="player"><a>Waived</a></td>
<td data-stat="team_id">BRK</td>
<td data-stat="y1" csk="2000000">$2,000,000</td>
<td class="right salary-tm" data-stat="y2" csk="2100000">$2,100,000</td>
<td data-stat="y3"></td></tr>
<tr><th data-stat="ranker">3</th><td data-append-csv="waived01" data-stat="player"><a>Waived</a></td>
<td data-stat="team_id">CHO</td>
<td data-stat="y1" csk="500000">$500,000</td><td data-stat="y2"></td><td data-stat="y3"></td></tr>
</tbody></table>"""


def test_contracts_long_format_with_options():
    df = parse_contracts(CONTRACTS_HTML, date(2026, 10, 1))
    star = df[df.bbref_id == "star01"].set_index("season")
    assert list(star.index.sort_values()) == ["2026-27", "2027-28"]
    assert star.loc["2026-27", "option_type"] == "none"
    assert star.loc["2027-28", "option_type"] == "player"
    assert star.loc["2027-28", "salary"] == 52_000_000


def test_contracts_duplicate_player_keeps_larger_salary():
    df = parse_contracts(CONTRACTS_HTML, date(2026, 10, 1))
    waived = df[(df.bbref_id == "waived01") & (df.season == "2026-27")]
    assert len(waived) == 1
    assert waived.iloc[0].salary == 2_000_000
    assert waived.iloc[0].bbref_team == "BRK"
    assert df[(df.bbref_id == "waived01") & (df.season == "2027-28")].option_type.item() == "team"
