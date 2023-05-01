#!/usr/bin/env python3
#
# Copyright (c) 2012-2022 Snowflake Computing Inc. All rights reserved.
#
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import sklearn.preprocessing._data as sklearn_preprocessing_data
from scipy import stats
from sklearn.preprocessing import RobustScaler as SklearnRobustScaler

from snowflake.ml.framework import utils
from snowflake.ml.framework.base import BaseEstimator, BaseTransformer
from snowflake.ml.utils import telemetry
from snowflake.snowpark import DataFrame

_PROJECT = "ModelDevelopment"
_SUBPROJECT = "Preprocessing"


class RobustScaler(BaseEstimator, BaseTransformer):
    def __init__(
        self,
        *,
        with_centering: bool = True,
        with_scaling: bool = True,
        quantile_range: Tuple[float, float] = (25.0, 75.0),
        unit_variance: bool = False,
        input_cols: Optional[Union[str, Iterable[str]]] = None,
        output_cols: Optional[Union[str, Iterable[str]]] = None,
        drop_input_cols: Optional[bool] = False,
    ) -> None:
        """Scale features using statistics that are robust to outliers.

        Args:
            with_centering: If True, center the data before scaling. This will cause transform
                to raise an exception when attempted on sparse matrices, because centering them
                entails building a dense matrix which in common use cases is likely to be too large
                to fit in memory.
            with_scaling: If True, scale the data to interquartile range.
            quantile_range: tuple (q_min, q_max), 0.0 < q_min < q_max < 100.0, default=(25.0, 75.0)
                Quantile range used to calculate scale_. By default this is equal to the IQR, i.e.,
                q_min is the first quantile and q_max is the third quantile.
            unit_variance: If True, scale data so that normally distributed features have a variance
                of 1. In general, if the difference between the x-values of q_max and q_min for a
                standard normal distribution is greater than 1, the dataset will be scaled down.
                If less than 1, the dataset will be scaled up.
            input_cols: Single or multiple input columns.
            output_cols: Single or multiple output columns.
            drop_input_cols: Remove input columns from output if set True. False by default.

        Attributes:
            center_: dict {column_name: The median value for each feature in the training set}.
            scale_: The (scaled) interquartile range for each feature in the training set.
        """
        self.with_centering = with_centering
        self.with_scaling = with_scaling
        self.quantile_range = quantile_range
        self.unit_variance = unit_variance

        self._state_is_set = False
        self._center: Dict[str, float] = {}
        self._scale: Dict[str, float] = {}

        l_range = self.quantile_range[0] / 100.0
        r_range = self.quantile_range[1] / 100.0
        self.custom_state: List[str] = [
            utils.NumericStatistics.MEDIAN.value,
            "SQL>>>percentile_cont(" + str(l_range) + ") within group (order by {col_name})",
            "SQL>>>percentile_cont(" + str(r_range) + ") within group (order by {col_name})",
        ]

        BaseEstimator.__init__(self, custom_state=self.custom_state)
        BaseTransformer.__init__(self, drop_input_cols=drop_input_cols)

        self.set_input_cols(input_cols)
        self.set_output_cols(output_cols)

    def _reset(self) -> None:
        """Reset internal data-dependent state of the scaler, if necessary.
        __init__ parameters are not touched.
        """
        super()._reset()
        self._center = {}
        self._scale = {}
        self._state_is_set = False

    @property
    def center_(self) -> Optional[Dict[str, float]]:
        return None if (not self.with_centering or not self._state_is_set) else self._center

    @property
    def scale_(self) -> Optional[Dict[str, float]]:
        return None if (not self.with_scaling or not self._state_is_set) else self._scale

    @telemetry.send_api_usage_telemetry(
        project=_PROJECT,
        subproject=_SUBPROJECT,
    )
    def fit(self, dataset: Union[DataFrame, pd.DataFrame]) -> "RobustScaler":
        """Compute center, scale and quantile values of the dataset.

        Args:
            dataset: Input dataset.

        Returns:
            Return self as fitted scaler.

        Raises:
            TypeError: If the input dataset is neither a pandas or Snowpark DataFrame.
        """
        super()._check_input_cols()
        self._reset()

        if isinstance(dataset, pd.DataFrame):
            self._fit_sklearn(dataset)
        elif isinstance(dataset, DataFrame):
            self._fit_snowpark(dataset)
        else:
            raise TypeError(
                f"Unexpected dataset type: {type(dataset)}."
                "Supported dataset types: snowpark.DataFrame, pandas.DataFrame."
            )
        self._is_fitted = True
        self._state_is_set = True

        return self

    def _fit_sklearn(self, dataset: pd.DataFrame) -> None:
        dataset = self._use_input_cols_only(dataset)
        sklearn_encoder = self._create_unfitted_sklearn_object()
        sklearn_encoder.fit(dataset[self.input_cols])

        for (i, input_col) in enumerate(self.input_cols):
            if self.with_centering:
                self._center[input_col] = float(sklearn_encoder.center_[i])
            if self.with_scaling:
                self._scale[input_col] = float(sklearn_encoder.scale_[i])

    def _fit_snowpark(self, dataset: DataFrame) -> None:
        computed_states = self._compute(dataset, self.input_cols, self.custom_state)

        q_min, q_max = self.quantile_range
        if not 0 <= q_min <= q_max <= 100:
            raise ValueError("Invalid quantile range: %s" % str(self.quantile_range))

        pcont_left = self.custom_state[1]
        pcont_right = self.custom_state[2]

        for input_col in self.input_cols:
            numeric_stats = computed_states[input_col]
            if self.with_centering:
                self._center[input_col] = float(numeric_stats[utils.NumericStatistics.MEDIAN])
            else:
                self._center[input_col] = 0

            if self.with_scaling:
                self._scale[input_col] = numeric_stats[pcont_right] - numeric_stats[pcont_left]
                self._scale[input_col] = sklearn_preprocessing_data._handle_zeros_in_scale(
                    self._scale[input_col], copy=False
                )
                if self.unit_variance:
                    adjust = stats.norm.ppf(q_max / 100.0) - stats.norm.ppf(q_min / 100.0)
                    self._scale[input_col] = self._scale[input_col] / adjust
            else:
                self._scale[input_col] = 1

    @telemetry.send_api_usage_telemetry(
        project=_PROJECT,
        subproject=_SUBPROJECT,
    )
    def transform(self, dataset: Union[DataFrame, pd.DataFrame]) -> Union[DataFrame, pd.DataFrame]:
        """Center and scale the data.

        Args:
            dataset: Input dataset.

        Returns:
            Output dataset.

        Raises:
            RuntimeError: If transformer is not fitted first.
            TypeError: If the input dataset is neither a pandas or Snowpark DataFrame.
        """
        if not self._is_fitted:
            raise RuntimeError("Transformer not fitted before calling transform().")
        super()._check_input_cols()
        super()._check_output_cols()

        if isinstance(dataset, DataFrame):
            output_df = self._transform_snowpark(dataset)
        elif isinstance(dataset, pd.DataFrame):
            output_df = self._transform_sklearn(dataset)
        else:
            raise TypeError(
                f"Unexpected dataset type: {type(dataset)}."
                "Supported dataset types: snowpark.DataFrame, pandas.DataFrame."
            )

        return self._drop_input_columns(output_df) if self._drop_input_cols is True else output_df

    def _transform_snowpark(self, dataset: DataFrame) -> DataFrame:
        """Center and scale the data on snowflake DataFrame.

        Args:
            dataset: Input dataset.

        Returns:
            Output dataset.
        """
        output_columns = []
        for _, input_col in enumerate(self.input_cols):
            col = dataset[input_col]
            if self.center_ is not None:
                col -= self.center_[input_col]
            if self.scale_ is not None:
                col /= float(self.scale_[input_col])
            output_columns.append(col)

        transformed_dataset = dataset.with_columns(self.output_cols, output_columns)
        return transformed_dataset

    def _create_unfitted_sklearn_object(self) -> SklearnRobustScaler:
        return SklearnRobustScaler(
            with_centering=self.with_centering,
            with_scaling=self.with_scaling,
            quantile_range=self.quantile_range,
            copy=True,
            unit_variance=self.unit_variance,
        )

    def _create_sklearn_object(self) -> SklearnRobustScaler:
        """Get an equivalent sklearn RobustScaler.

        Returns:
            Sklearn RobustScaler.

        Raises:
            RuntimeError: If transformer is not fitted first.
        """
        if self.scale_ is None or self.center_ is None:
            raise RuntimeError("Transformer not fitted before calling transform().")

        scaler = self._create_unfitted_sklearn_object()
        if self._is_fitted:
            scaler.scale_ = self._convert_attribute_dict_to_ndarray(self.scale_, np.float64)
            scaler.center_ = self._convert_attribute_dict_to_ndarray(self.center_, np.float64)
        return scaler