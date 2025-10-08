import os
from datetime import date
from src.trading.utils.config import get_config_file_default, load_config
from src.trading.data.data import get_all_forex_data_on_date
import src as constants

data_list = get_all_forex_data_on_date()
print(data_list)

