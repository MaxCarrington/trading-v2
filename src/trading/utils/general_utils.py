import re 

# Validate if a value matches a given regex pattern
def is_valid_regex(value, regex):
    return bool(re.fullmatch(regex, value))

# Define trading sessions
def get_trading_session_folder(time):
    if time.hour >= 7 and time.hour < 15:  # London session
        return "London"
    elif time.hour >= 15 and time.hour < 23:  # New York session
        return "New_York"
    else:  # Asian session
        return "Asian"
