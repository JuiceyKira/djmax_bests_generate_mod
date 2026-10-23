import math
import pandas as pd
from typing import Literal
from decimal import Decimal

from .. import util
from . import data_converter



class AnalyzeUtil():
    # The merged frame is shared by every analyzer in the process. It is loaded from the
    # records_db store on first use, or injected through use_varecords() — and it is loaded only
    # once, because the renderers construct an AnalyzeUtil per floor and a reload re-reads the
    # whole store.
    merged_df: pd.DataFrame | None = None

    # One shared analyzer per button mode for the whole process. The renderers spawn repeatedly
    # (draw_cover and draw_modecard each create a 4B analyzer, every scorelist chart respawns),
    # and a fresh instance would redo its spawn slice and recompute every cached view
    # (topn, djpower_theo, tags_skill) from scratch. The analyzers are read-only views over
    # data that never changes, so sharing them is safe; use_varecords() drops them all.
    _analyzers: dict[int, RecordAnalyzer] = {}


    def __init__(self) -> None:
        if AnalyzeUtil.merged_df is None:
            AnalyzeUtil.merged_df = data_converter.load_records_db()


    def spawn_analyzer(self, bmode: int) -> RecordAnalyzer:
        if bmode not in AnalyzeUtil._analyzers:
            df = AnalyzeUtil.merged_df
            AnalyzeUtil._analyzers[bmode] = RecordAnalyzer(bmode, df[df['button'] == bmode])
        return AnalyzeUtil._analyzers[bmode]


    def spawn_analyzer_full(self) -> RecordAnalyzer:
        # 99 = no button mode: the analyzer spans all four.
        if 99 not in AnalyzeUtil._analyzers:
            AnalyzeUtil._analyzers[99] = RecordAnalyzer(99, AnalyzeUtil.merged_df)
        return AnalyzeUtil._analyzers[99]


    @classmethod
    def use_varecords(cls, records: dict) -> None:
        """Point every analyzer at `records` ({bmode: raw response text}) instead of the stored
        records_db.

        The inspector scripts (`inspect_runrun.py`, `inspect_summary.py`, `inspect_target.py`)
        download another account's records and inject them here, so the local record store is
        neither read nor written while looking at somebody else's account. The mapping may be
        partial — inspect_runrun and inspect_target fetch just the button mode they render —
        and the analyzers then only cover the modes it holds. Shared analyzers belonging to
        the previous frame are dropped with it.
        """
        cls.merged_df = data_converter.records_db_from_varecord(records)
        cls._analyzers.clear()


class RecordAnalyzer:

    def __init__(self, bmode: int, data: pd.DataFrame):
        self.data = data
        self.bmode = bmode
        # The renderers query the same filtered views over and over (every draw_* helper
        # re-reads several djpower/topn properties). self.data never changes after
        # construction, so these per-instance caches can never go stale.
        self._topn_cache: dict[tuple, pd.DataFrame] = {}
        self._djpower_theo: Decimal | None = None

    # ======================================================================
    # Filter
    # ======================================================================

    def filter(self, bmode=None, pattern=None, is_sc=None,
               level_min=None, level_max=None, dlc_code=None,
               is_new=None, floor_name=None, title_contains=None,
               cleared=None, score_min=None, score_max=None,
               rating_min=None, rating_max=None, max_combo=None,
               tags: dict | None = None) -> pd.DataFrame:
        """
        tags 参数是一个条件字典，例如 {'Jack': 3, 'Stream': (2, 3)}，
        表示该行 tags dict 中必须满足这些键值条件。

        All conditions are AND-ed into one boolean mask so the frame is scanned once,
        instead of once per condition.
        """
        df = self.data
        mask = pd.Series(True, index=df.index)

        if bmode is not None:
            mask &= df['button'].isin(self._as_list(bmode))
        if pattern is not None:
            mask &= df['pattern'].isin(
                [str(p).upper() for p in self._as_list(pattern)])
        if is_sc is not None:
            mask &= df['is_sc'] == is_sc
        if dlc_code is not None:
            mask &= df['dlc_code'].isin(self._as_list(dlc_code))
        if is_new is not None:
            mask &= df['is_new'] == bool(is_new)
        if floor_name is not None:
            mask &= df['floor_name'] == str(floor_name)
        if title_contains is not None:
            mask &= df['title'].str.contains(title_contains, case=False, na=False)
        if cleared is not None:
            mask &= df['cleared'] == bool(cleared)
        if score_min is not None:
            mask &= df['score'] >= score_min
        if score_max is not None:
            mask &= df['score'] <= score_max
        if rating_min is not None:
            mask &= df['rating'] >= rating_min
        if rating_max is not None:
            mask &= df['rating'] <= rating_max
        if max_combo is not None:
            mask &= df['max_combo'] == bool(max_combo)
        if level_min is not None:
            mask &= df['level'] >= level_min
        if level_max is not None:
            mask &= df['level'] <= level_max
        if tags:
            mask &= df['tags'].apply(lambda d: self._match_tags(d, tags))
        return df[mask].copy()


    @staticmethod
    def _as_list(v):
        if isinstance(v, (list, tuple, set)):
            return list(v)
        return [v]


    @staticmethod
    def _match_tags(tag_dict, conditions):
        for k, v in conditions.items():
            if k not in tag_dict:
                return False
            if isinstance(v, (list, tuple, set)):
                if tag_dict[k] not in v:
                    return False
            elif callable(v):
                if not v(tag_dict[k]):
                    return False
            else:
                if tag_dict[k] != v:
                    return False
        return True
    
    # ======================================================================
    # Analyze
    # ======================================================================

    def get_cleared(self, **kwargs) -> pd.DataFrame:
        return self.filter(cleared=True, **kwargs)

    # ---------------- STATUS ----------------

    def stats_cleared(self, attribute:list=['button','is_sc','level'], **filter_kwargs) -> pd.DataFrame:
        df = self.get_cleared(**filter_kwargs)
        df['max_combo'] = df['max_combo'].astype(int)
        df['_perfect'] = (df['score'] == 100).astype(int)
        stats = df.groupby(attribute).agg(
            cleared=('songid', 'count'),
            avg_score=('score', 'mean'),
            max_score=('score', 'max'),
            min_score=('score', 'min'),
            avg_djpower=('djpower', 'mean'),
            max_djpower=('djpower', 'max'),
            max_combo=('max_combo', 'sum'),
            perfect_play=('_perfect', 'sum')
        ).reset_index()

        if 'pattern' in stats.columns:
            stats['pattern'] = pd.Categorical(
                stats['pattern'],
                categories=['NM', 'HD', 'MX', 'SC'],
                ordered=True,
            )
        priority = ['songid', 'button', 'pattern', 'level', 'title']
        sort_keys = [k for k in priority if k in attribute]
        stats = stats.sort_values(sort_keys, kind='stable').reset_index(drop=True)
        return stats        


    def topn_attribute(self, attribute:Literal['score','djpower','max_djpower','rating','floor_name'], n=100, **kwargs) -> pd.DataFrame:
        """Top-n among the cleared records matching **kwargs, cached per (attribute, n, kwargs)."""
        key_parts = self._cache_key(kwargs)
        if key_parts is None:                       # unhashable kwarg (e.g. a tags dict) — no cache
            return self.get_cleared(**kwargs).nlargest(n, attribute)
        key = (attribute, n) + key_parts
        if key not in self._topn_cache:
            self._topn_cache[key] = self.get_cleared(**kwargs).nlargest(n, attribute)
        return self._topn_cache[key]


    def _max_djpower_topn(self, is_new: bool, n: int) -> pd.DataFrame:
        """Top-n by theoretical max_djpower over ALL patterns (cleared or not) — the shared
        base of the djpower_theo family, cached."""
        key = ('max_djpower_theo', is_new, n)
        if key not in self._topn_cache:
            self._topn_cache[key] = self.filter(is_new=is_new).nlargest(n, 'max_djpower')
        return self._topn_cache[key]


    @staticmethod
    def _cache_key(kwargs) -> tuple | None:
        """A hashable key for filter kwargs, or None when a value is not hashable."""
        items = []
        for k, v in kwargs.items():
            if isinstance(v, (list, tuple, set)):
                v = tuple(v)                        # filter() treats these alike anyway
            try:
                hash(v)
            except TypeError:
                return None
            items.append((k, v))
        return tuple(sorted(items, key=lambda kv: kv[0]))


    def highest_condition(self, **kwargs):
        """Return highest record in filtered records"""
        nsc_df = self.filter(is_sc=False, **kwargs)
        sc_df = self.filter(is_sc=True, **kwargs)
        return comparedf_sc_nsc(nsc_df, sc_df)


    # ----------------TAGS----------------
    
    def filter_tags(self, **conditions) -> pd.DataFrame:
        """按 tag 筛选，例如 analyzer.filter_by_tags(Jack=3, Stream=(2, 3))"""
        return self.filter(tags=conditions)
    
    
    def _explode(self, col: str, prefix: str, **filter_kwargs) -> pd.DataFrame:
        """把 tags / tags_score 这类 dict 列展开为多列，便于做聚合分析。"""
        df = self.filter(**filter_kwargs) if filter_kwargs else self.data.copy()
        exploded = (df[col]
                    .apply(lambda d: d if isinstance(d, dict) else {})
                    .apply(pd.Series)
                    .add_prefix(prefix))
        return pd.concat([df.drop(columns=[col]), exploded], axis=1)


    def explode_tags(self, **filter_kwargs) -> pd.DataFrame:
        """把 tags dict 展开为 tagsfull_* 多列。"""
        return self._explode('tags', 'tagsfull_', **filter_kwargs)


    def explode_tags_score(self, **filter_kwargs) -> pd.DataFrame:
        """把 tags_score dict 展开为 score_* 多列。"""
        return self._explode('tags_score', 'score_', **filter_kwargs)


    def _tags_top_sum(self, col: str, prefix: str, n: int, **filter_kwargs) -> pd.Series:
        """展开 dict 列后，对每个前缀列取降序前 n 项求和，tags_top_sum / tags_score_top_sum 共用。"""
        exploded = self._explode(col, prefix, **filter_kwargs)

        result = {}
        for c in (c for c in exploded.columns if c.startswith(prefix)):
            s = pd.to_numeric(exploded[c], errors='coerce').dropna()
            result[c[len(prefix):]] = float(s.nlargest(n).sum()) if len(s) else 0.0

        return pd.Series(result, name=f'top{n}_sum')


    def tags_top_sum(self, n: int = 30, **filter_kwargs) -> pd.Series:
        """
        对每个 tag 的 djpower 加权占比（tags 列）取降序前 n 项求和。
        返回 Series：index 为特征名，值为前 n 项之和。
        """
        return self._tags_top_sum('tags', 'tagsfull_', n, **filter_kwargs)


    def tags_score_top_sum(self, n: int = 30, **filter_kwargs) -> pd.Series:
        """
        对每个 tag 的得分贡献（tags_score 列）取降序前 n 项求和。
        返回 Series：index 为特征名，值为前 n 项之和。
        """
        return self._tags_top_sum('tags_score', 'score_', n, **filter_kwargs)

    # ----------------PROPERTIES----------------

    @property
    def count_cleared(self) ->int:
        return int(self.data['cleared'].sum())
    
    @property
    def count_max_combo(self) ->int:
        return int(self.data['max_combo'].sum())
    
    @property
    def count_perfect_play(self) ->int:
        return int((self.data['score'] == 100).sum())

    @property
    def count_total(self) ->int:
        return int(len(self.data))

    @property
    def count_total_basic(self) ->int:
        df= self.topn_attribute('djpower', 70, is_new = False)
        retval = int(df['djpower'].count())
        return retval
    
    @property
    def count_total_new(self) ->int:
        df= self.topn_attribute('djpower', 30, is_new = True)
        retval = int(df['djpower'].count())
        return retval
    
    @property
    def count_pattern(self) ->list:
        """['NM','HD','MX','SC']"""
        retval = self.data['pattern'].value_counts().reindex(['NM','HD','MX','SC'])
        return retval.to_list()
    
    @property
    def avg_score(self) ->float:
        return self.get_cleared()['score'].mean()
    
    @property
    def djpower_basic_raw(self) -> Decimal:
        df= self.topn_attribute('djpower', 70, is_new = False)
        retval = Decimal(df['djpower'].sum())
        return retval if retval != 0 else Decimal(0)

    @property
    def djpower_new_raw(self) -> Decimal:
        df= self.topn_attribute('djpower', 30, is_new = True)
        retval = Decimal(df['djpower'].sum())
        return retval if retval != 0 else Decimal(0)
   
    @property
    def djpower_basic(self) -> Decimal:
        return util.cut_digits(self.djpower_basic_raw * self.djpower_convert_constant, 4)

    @property
    def djpower_new(self) -> Decimal:
        return util.cut_digits(self.djpower_new_raw * self.djpower_convert_constant, 4)
    
    @property
    def djpower_raw(self) -> Decimal:
        retval = self.djpower_basic_raw + self.djpower_new_raw
        return util.cut_digits(retval, 4)
    
    @property
    def djpower(self) -> Decimal:
        ret_val = util.cut_digits(self.djpower_raw * self.djpower_convert_constant, 4)
        if ret_val > Decimal("10000.0000"):
            return Decimal("10000.0000")
        return ret_val

    @property
    def djpower_perfect_basic(self) -> Decimal:
        df= self.topn_attribute('djpower', 70, is_new = False)

        retval = Decimal(df['max_djpower'].sum())
        return util.cut_digits(retval * self.djpower_convert_constant, 4)

    @property
    def djpower_perfect_new(self) -> Decimal:
        df= self.topn_attribute('djpower', 30, is_new = True)
        retval = Decimal(df['max_djpower'].sum())
        return util.cut_digits(retval * self.djpower_convert_constant, 4)

    @property
    def djpower_theo(self) -> Decimal:
        if self._djpower_theo is None:
            retval = Decimal(self._max_djpower_topn(False, 70)['max_djpower'].sum())
            retval += Decimal(self._max_djpower_topn(True, 30)['max_djpower'].sum())
            self._djpower_theo = util.cut_digits(retval, 4)
        return self._djpower_theo

    @property
    def djpower_convert_constant(self) -> Decimal:
        return 10000 / self.djpower_theo

    @property
    def djpower_theo_basic(self) -> Decimal:
        retval = Decimal(self._max_djpower_topn(False, 70)['max_djpower'].sum())
        return util.cut_digits(retval * self.djpower_convert_constant, 4)

    @property
    def djpower_theo_new(self) -> Decimal:
        retval = Decimal(self._max_djpower_topn(True, 30)['max_djpower'].sum())
        return util.cut_digits(retval * self.djpower_convert_constant, 4)

    @property
    def highest_cleared(self):
        return self.highest_condition(cleared=True)
   
    @property
    def highest_max_combo(self):
        return self.highest_condition(cleared=True, max_combo=True, score_max=99.99)

    @property
    def highest_perfect_play(self):
        return self.highest_condition(cleared=True, score_min=100)

    @property
    def tags_skill(self):
        tags_score = self.tags_score_top_sum()
        tags_score_full = self.tags_top_sum()
        tags_score = tags_score.div(tags_score_full).mul(3)
        return tags_score


# ======================================================================
# Other tools
# ======================================================================

def level_comparer(level, level_sc):
    """Compare NonSC level and SC level, return highest level and SC bool"""
    if level_sc == 0:
        if level == 0: return (0, False)
        else: return (level, False)
    elif level == 0: return (level_sc, True)

    level_coeff = util.diff_coeff(level, False)
    level_sc_coeff = util.diff_coeff(level_sc, True)
    if level_coeff <= level_sc_coeff: return (level_sc, True)
    else: return (level, False)


def comparedf_sc_nsc(nsc_df:pd.DataFrame, sc_df:pd.DataFrame) ->pd.DataFrame:
    """Compare records in SC df and NonSC df, return highest record"""
    level_nsc = 0 if nsc_df.empty else nsc_df['level'].max()
    level_sc = 0 if sc_df.empty else sc_df['level'].max()
    level_high = level_comparer(level_nsc, level_sc)
    if level_high[1]:df = sc_df
    else:df = nsc_df
    return df[df['level'] == level_high[0]].nlargest(1,'rating')


_VAL_94_5 = (24 / 135 * math.exp(8 / 9 * (94.5 - 95)) + 0.125)
_VAL_95_5 = (24 / 135 * math.exp(2 / 3 * (95.5 - 95)) + 0.125)
_VAL_96   = (24 / 135 * math.exp(2 / 3 * (96 - 95)) + 0.125)
_VAL_96_5 = (80 / 297 * (math.log(96.5 - 95) - math.log(5)) + 10 / 11) * (3 * 96.5 - 250.5) / 40
def djpower_calc_opt(score: float, max_djpower: float) -> Decimal:
    if score <= 90:
        djpow_ratio = 0.0
    elif score <= 94.5:
        djpow_ratio = (24 / 135 * math.exp(8 / 9 * (score - 95)) + 0.125)
    elif score < 95.5:
        djpow_ratio = _VAL_94_5 + (_VAL_95_5 - _VAL_94_5) * (score - 94.5) + (score - 94.5) * (score - 95.5) / 30
    elif score <= 96:
        djpow_ratio = (24 / 135 * math.exp(2 / 3 * (score - 95))) + 0.125
    elif score < 96.5:
        djpow_ratio = _VAL_96 + 2 * (_VAL_96_5 - _VAL_96) * (score - 96)
    else:
        common_log_term = (80 / 297 * (math.log(score - 95) - math.log(5)) + 10 / 11)
        if score < 97.5:
            djpow_ratio = common_log_term * (3 * score - 250.5) / 40
        elif score < 98:
            djpow_ratio = common_log_term * (score - 76.5) / 20
        elif score < 98.5:
            djpow_ratio = common_log_term * (3 * score - 186.5) / 100
        elif score < 99:
            djpow_ratio = common_log_term * (score - 44) / 50
        elif score < 100:
            djpow_ratio = 8 / 27 * (math.log(score - 95) - math.log(5)) + 1
        else:  # score == 100
            djpow_ratio = 1.0

    final_score = djpow_ratio * max_djpower
    return Decimal(str(final_score)).quantize(Decimal('0.0001'), rounding='ROUND_FLOOR')
