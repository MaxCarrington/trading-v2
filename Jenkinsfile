pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '40'))
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Matrix Backtests') {
            matrix {
                axes {
                    // Core axes
                    axis { name 'TIMEFRAME'; values 'M1'}
                    axis { name 'RSI_LOOKBACK'; values '30' }
                    axis { name 'MA_LOOKBACK'; values '30' }

                    // Threshold sweeps
                    axis { name 'MA_THRESH'; values '0.6' }
                    axis { name 'OVERBOUGHT'; values '60' }
                    axis { name 'OVERSOLD'; values '40', }
                    axis { name 'MOMENTUM_LEN'; values '0.9'}

                    // Filters
                    axis { name 'USE_VOL'; values 'true', 'false' }
                    axis { name 'USE_RSI'; values 'true', 'false' }
                    axis { name 'USE_MA'; values 'true', 'false' }
                    axis { name 'USE_MOMENTUM'; values 'true', 'false' }
                }

                agent any
                stages {
                    stage('Setup Environment') {
                        steps {
                            sh '''
                                source ~/anaconda3/bin/activate trading-py311 || true
                                pip install -r requirements.txt
                            '''
                        }
                    }

                    stage('Render Config') {
                        steps {
                            sh '''
                                mkdir -p run_configs
                                envsubst < configs/momentum_template.yaml > run_configs/config_${TIMEFRAME}_${RSI_LOOKBACK}_${STOP_LOSS_TYPE}_${TAKE_PROFIT_TYPE}_${USE_VOL}_${VOL_WINDOW}_${USE_RSI}_${USE_MA}_${USE_MOMENTUM}_${MAX_OPEN_POS}_${POS_SIZE_TYPE}_${POS_SIZE}.yaml
                            '''
                        }
                    }

                    stage('Run Backtest') {
                        steps {
                            sh '''
                                TS=$(date -u +"%Y%m%dT%H%M%SZ")
                                OUTDIR="results/${TIMEFRAME}/${RSI_LOOKBACK}/${STOP_LOSS_TYPE}/${TAKE_PROFIT_TYPE}/${USE_VOL}_${VOL_WINDOW}/${USE_RSI}_${USE_MA}_${USE_MOMENTUM}/${MAX_OPEN_POS}/${POS_SIZE_TYPE}_${POS_SIZE}/${TS}"
                                mkdir -p "${OUTDIR}"
                                python scripts/run_backtest.py --config run_configs/config_${TIMEFRAME}_${RSI_LOOKBACK}_${STOP_LOSS_TYPE}_${TAKE_PROFIT_TYPE}_${USE_VOL}_${VOL_WINDOW}_${USE_RSI}_${USE_MA}_${USE_MOMENTUM}_${MAX_OPEN_POS}_${POS_SIZE_TYPE}_${POS_SIZE}.yaml --outdir "${OUTDIR}"
                                cp run_configs/config_${TIMEFRAME}_${RSI_LOOKBACK}_${STOP_LOSS_TYPE}_${TAKE_PROFIT_TYPE}_${USE_VOL}_${VOL_WINDOW}_${USE_RSI}_${USE_MA}_${USE_MOMENTUM}_${MAX_OPEN_POS}_${POS_SIZE_TYPE}_${POS_SIZE}.yaml "${OUTDIR}/resolved_config.yaml"
                            '''
                        }
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'results/**', fingerprint: true
        }
    }
}
