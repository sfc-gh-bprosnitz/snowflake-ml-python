import os
import tempfile
import warnings

import numpy as np
import pandas as pd
from absl.testing import absltest
from sklearn import datasets, ensemble, linear_model, multioutput

from snowflake.ml.model import model_signature, type_hints as model_types
from snowflake.ml.model._packager import model_packager


class SKLearnHandlerTest(absltest.TestCase):
    def test_skl_multiple_output_proba(self) -> None:
        iris_X, iris_y = datasets.load_iris(return_X_y=True)
        target2 = np.random.randint(0, 6, size=iris_y.shape)
        dual_target = np.vstack([iris_y, target2]).T
        model = multioutput.MultiOutputClassifier(ensemble.RandomForestClassifier(random_state=42))
        iris_X_df = pd.DataFrame(iris_X, columns=["c1", "c2", "c3", "c4"])
        model.fit(iris_X_df[:-10], dual_target[:-10])
        with tempfile.TemporaryDirectory() as tmpdir:
            s = {"predict_proba": model_signature.infer_signature(iris_X_df, model.predict_proba(iris_X_df))}
            model_packager.ModelPackager(os.path.join(tmpdir, "model1")).save(
                name="model1",
                model=model,
                signatures=s,
                metadata={"author": "halu", "version": "1"},
                conda_dependencies=["scikit-learn"],
            )

            orig_res = model.predict_proba(iris_X_df[-10:])

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1"))
            pk.load()
            assert pk.model
            assert pk.meta
            assert isinstance(pk.model, multioutput.MultiOutputClassifier)
            loaded_res = pk.model.predict_proba(iris_X_df[-10:])
            np.testing.assert_allclose(np.hstack(orig_res), np.hstack(loaded_res))

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1"))
            pk.load(as_custom_model=True)
            assert pk.model
            assert pk.meta
            predict_method = getattr(pk.model, "predict_proba", None)
            assert callable(predict_method)
            udf_res = predict_method(iris_X_df[-10:])
            np.testing.assert_allclose(
                np.hstack(orig_res), np.hstack([np.array(udf_res[col].to_list()) for col in udf_res])
            )

            with self.assertRaises(ValueError):
                model_packager.ModelPackager(local_dir_path=os.path.join(tmpdir, "model1_no_sig_bad")).save(
                    name="model1_no_sig_bad",
                    model=model,
                    sample_input=iris_X_df,
                    metadata={"author": "halu", "version": "1"},
                    options=model_types.SKLModelSaveOptions({"target_methods": ["random"]}),
                )

            model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig")).save(
                name="model1_no_sig",
                model=model,
                sample_input=iris_X_df,
                metadata={"author": "halu", "version": "1"},
            )

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig"))
            pk.load()
            assert pk.model
            assert pk.meta
            assert isinstance(pk.model, multioutput.MultiOutputClassifier)
            np.testing.assert_allclose(
                np.hstack(model.predict_proba(iris_X_df[-10:])), np.hstack(pk.model.predict_proba(iris_X_df[-10:]))
            )
            np.testing.assert_allclose(model.predict(iris_X_df[-10:]), pk.model.predict(iris_X_df[-10:]))
            self.assertEqual(s["predict_proba"], pk.meta.signatures["predict_proba"])

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig"))
            pk.load(as_custom_model=True)
            assert pk.model
            assert pk.meta

            predict_method = getattr(pk.model, "predict_proba", None)
            assert callable(predict_method)
            udf_res = predict_method(iris_X_df[-10:])
            np.testing.assert_allclose(
                np.hstack(model.predict_proba(iris_X_df[-10:])),
                np.hstack([np.array(udf_res[col].to_list()) for col in udf_res]),
            )

            predict_method = getattr(pk.model, "predict", None)
            assert callable(predict_method)
            np.testing.assert_allclose(model.predict(iris_X_df[-10:]), predict_method(iris_X_df[-10:]).to_numpy())

    def test_skl(self) -> None:
        iris_X, iris_y = datasets.load_iris(return_X_y=True)
        regr = linear_model.LinearRegression()
        iris_X_df = pd.DataFrame(iris_X, columns=["c1", "c2", "c3", "c4"])
        regr.fit(iris_X_df, iris_y)
        with tempfile.TemporaryDirectory() as tmpdir:
            s = {"predict": model_signature.infer_signature(iris_X_df, regr.predict(iris_X_df))}
            with self.assertRaises(ValueError):
                model_packager.ModelPackager(os.path.join(tmpdir, "model1")).save(
                    name="model1",
                    model=regr,
                    signatures={**s, "another_predict": s["predict"]},
                    metadata={"author": "halu", "version": "1"},
                )

            model_packager.ModelPackager(os.path.join(tmpdir, "model1")).save(
                name="model1",
                model=regr,
                signatures=s,
                metadata={"author": "halu", "version": "1"},
            )

            with warnings.catch_warnings():
                warnings.simplefilter("error")

                pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1"))
                pk.load()
                assert pk.model
                assert pk.meta
                assert isinstance(pk.model, linear_model.LinearRegression)
                np.testing.assert_allclose(np.array([-0.08254936]), pk.model.predict(iris_X_df[:1]))

                pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1"))
                pk.load(as_custom_model=True)
                assert pk.model
                assert pk.meta
                predict_method = getattr(pk.model, "predict", None)
                assert callable(predict_method)
                np.testing.assert_allclose(np.array([[-0.08254936]]), predict_method(iris_X_df[:1]))

            model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig")).save(
                name="model1_no_sig",
                model=regr,
                sample_input=iris_X_df,
                metadata={"author": "halu", "version": "1"},
            )

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig"))
            pk.load()
            assert pk.model
            assert pk.meta
            assert isinstance(pk.model, linear_model.LinearRegression)
            np.testing.assert_allclose(np.array([-0.08254936]), pk.model.predict(iris_X_df[:1]))
            self.assertEqual(s["predict"], pk.meta.signatures["predict"])

            pk = model_packager.ModelPackager(os.path.join(tmpdir, "model1_no_sig"))
            pk.load(as_custom_model=True)
            assert pk.model
            assert pk.meta
            predict_method = getattr(pk.model, "predict", None)
            assert callable(predict_method)
            np.testing.assert_allclose(np.array([[-0.08254936]]), predict_method(iris_X_df[:1]))


if __name__ == "__main__":
    absltest.main()
