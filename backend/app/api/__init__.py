"""
API路由模块
"""

from flask import Blueprint

graph_bp = Blueprint('graph', __name__)
simulation_bp = Blueprint('simulation', __name__)
report_bp = Blueprint('report', __name__)
country_packs_bp = Blueprint('country_packs', __name__)

from . import graph  # noqa: E402, F401
from . import simulation  # noqa: E402, F401
from . import report  # noqa: E402, F401
from . import country_packs  # noqa: E402, F401
from .channels import channels_bp, swarm_bp  # noqa: E402, F401
from .analytics import analytics_bp  # noqa: E402, F401
from .v3 import v3_bp  # noqa: E402, F401

