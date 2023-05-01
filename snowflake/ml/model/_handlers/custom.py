import os
from typing import Any

import cloudpickle

from snowflake.ml._internal import file_utils, type_utils
from snowflake.ml.model import model_handler, model_meta as model_meta_api, model_types
from snowflake.ml.model._handlers import _base


class _CustomModelHandler(_base._ModelHandler):
    """Handler for custom model."""

    handler_type = "custom"

    @staticmethod
    def can_handle(model: model_types.ModelType) -> bool:
        return bool(type_utils.LazyType("snowflake.ml.model.custom_model.CustomModel").isinstance(model))

    @staticmethod
    def _save_model(
        name: str,
        model: model_types.ModelType,
        model_meta: model_meta_api.ModelMetadata,
        model_blobs_dir_path: str,
        **kwargs: Any,
    ) -> None:
        from snowflake.ml.model import custom_model

        assert isinstance(model, custom_model.CustomModel)

        model_blob_path = os.path.join(model_blobs_dir_path, name)
        os.makedirs(model_blob_path, exist_ok=True)
        if model.context.artifacts:
            artifacts_path = os.path.join(model_blob_path, _CustomModelHandler.MODEL_ARTIFACTS_DIR)
            os.makedirs(artifacts_path, exist_ok=True)
            for _name, uri in model.context.artifacts.items():
                file_utils.copy_file_or_tree(uri, artifacts_path)

        # Save sub-models
        if model.context.model_refs:
            for sub_name, model_ref in model.context.model_refs.items():
                handler = model_handler._find_handler(model_ref.model)
                assert handler is not None
                handler._save_model(sub_name, model_ref.model, model_meta, model_blobs_dir_path)

        with open(os.path.join(model_blob_path, _CustomModelHandler.MODEL_BLOB_FILE), "wb") as f:
            cloudpickle.dump(model, f)
        model_meta.models[name] = model_meta_api._ModelBlobMetadata(
            name=name,
            model_type=_CustomModelHandler.handler_type,
            path=_CustomModelHandler.MODEL_BLOB_FILE,
            artifacts={
                name: os.path.join(_CustomModelHandler.MODEL_ARTIFACTS_DIR, os.path.basename(uri))
                for name, uri in model.context.artifacts.items()
            },
        )

    @staticmethod
    def _load_model(
        name: str, model_meta: model_meta_api.ModelMetadata, model_blobs_dir_path: str
    ) -> model_types.ModelType:
        from snowflake.ml.model import custom_model

        model_blob_path = os.path.join(model_blobs_dir_path, name)
        if not hasattr(model_meta, "models"):
            raise ValueError("Ill model metadata found.")
        model_blobs_metadata = model_meta.models

        if name not in model_blobs_metadata:
            raise ValueError(f"Blob of model {name} does not exist.")
        model_blob_metadata = model_blobs_metadata[name]
        model_blob_filename = model_blob_metadata.path
        with open(os.path.join(model_blob_path, model_blob_filename), "rb") as f:
            m = cloudpickle.load(f)
        ModelClass = type(m)
        artifacts_meta = model_blob_metadata.artifacts
        artifacts = {name: os.path.join(model_blob_path, rel_path) for name, rel_path in artifacts_meta.items()}
        models = dict()
        for sub_model_name, _ref in m.context.model_refs.items():
            model_type = model_meta.models[sub_model_name].model_type
            handler = model_handler._load_handler(model_type)
            assert handler
            sub_model = handler._load_model(
                name=sub_model_name,
                model_meta=model_meta,
                model_blobs_dir_path=model_blobs_dir_path,
            )
            models[sub_model_name] = sub_model
        ctx = custom_model.ModelContext(artifacts=artifacts, models=models)
        model = ModelClass(ctx)
        return model