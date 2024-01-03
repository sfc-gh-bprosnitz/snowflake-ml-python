from typing import TypedDict

from typing_extensions import Required

from snowflake.ml.model import model_signature


class ModelFunctionInfo(TypedDict):
    """Function information.

    Attributes:
        name: Name of the function to be called via SQL.
        target_method: actual target method name to be called.
        signature: The signature of the model method.
    """

    name: Required[str]
    target_method: Required[str]
    signature: Required[model_signature.ModelSignature]