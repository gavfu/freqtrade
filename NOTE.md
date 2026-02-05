
# Initialize configuration and start trade
```sh
# activate virtual environment
source ./.venv/bin/activate

# initialize user folder
freqtrade create-userdir --userdir user_data

# create a new configuration file
freqtrade new-config --config user_data/config.json

# run SampleStrategy
freqtrade trade --config user_data/config.json --strategy SampleStrategy
```
