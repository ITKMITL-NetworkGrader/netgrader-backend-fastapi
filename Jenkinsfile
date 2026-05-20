pipeline {
    agent any

    environment {
        COMPOSE_DIR = '/home/netgrader/netgrader/netgrader-container'
        REPLICAS    = '8'
    }

    stages {
        stage('Setup') {
            steps {
                script {
                    def branch = env.BRANCH_NAME ?: 'main'
                    def isProd = (branch == 'main')
                    env.ENV_NAME       = isProd ? 'prod' : 'dev'
                    env.IMAGE_NAME     = "netgrader-backend-fastapi:${env.ENV_NAME}"
                    env.SERVICE_NAME   = isProd ? 'backend-fastapi' : 'backend-fastapi-dev'
                    env.COMPOSE_FILE   = isProd ? 'docker-compose.yml' : 'docker-compose-dev.yml'
                    env.BACKUP_IMAGE   = "netgrader-backend-fastapi-backup-${env.ENV_NAME}-${env.BUILD_NUMBER}"
                    env.PREVIOUS_IMAGE = "netgrader-backend-fastapi-backup-${env.ENV_NAME}-${(env.BUILD_NUMBER.toInteger() - 1)}"
                    env.SCALE          = isProd ? env.REPLICAS : '1'
                    echo "[SETUP] Branch: ${branch} | Env: ${env.ENV_NAME} | Image: ${env.IMAGE_NAME} | Replicas: ${env.SCALE}"
                }
            }
        }

        stage('Backup Current Image') {
            steps {
                script {
                    sh "docker tag ${env.IMAGE_NAME} ${env.BACKUP_IMAGE} || echo 'No existing image to backup'"
                }
            }
        }

        stage('Build Image') {
            steps {
                script {
                    def buildResult = sh(
                        script: "docker build -t ${env.IMAGE_NAME} ${env.WORKSPACE}",
                        returnStatus: true
                    )
                    if (buildResult != 0) {
                        error("Docker build failed with exit code ${buildResult}")
                    }
                    echo "Build completed: ${env.IMAGE_NAME}"
                }
            }
        }

        stage('Deploy') {
            steps {
                script {
                    sh """
                        cd ${COMPOSE_DIR}
                        docker compose -f ${env.COMPOSE_FILE} down ${env.SERVICE_NAME}
                        docker compose -f ${env.COMPOSE_FILE} up -d --scale ${env.SERVICE_NAME}=${env.SCALE} ${env.SERVICE_NAME}
                    """
                }
            }
        }

        stage('Health Check') {
            steps {
                script {
                    sleep(time: 45, unit: 'SECONDS')
                    def maxAttempts = 8
                    retry(maxAttempts) {
                        try {
                            def runningCount = sh(
                                script: """
                                    cd ${COMPOSE_DIR}
                                    docker compose -f ${env.COMPOSE_FILE} ps ${env.SERVICE_NAME} | grep -c "Up" || echo "0"
                                """,
                                returnStdout: true
                            ).trim().toInteger()

                            echo "Running replicas: ${runningCount}/${env.SCALE}"
                            if (runningCount < env.SCALE.toInteger()) {
                                error("Only ${runningCount}/${env.SCALE} replicas running")
                            }

                            def containerIds = sh(
                                script: "cd ${COMPOSE_DIR} && docker compose -f ${env.COMPOSE_FILE} ps -q ${env.SERVICE_NAME}",
                                returnStdout: true
                            ).trim().split('\n')

                            def healthResponse = sh(
                                script: "docker exec ${containerIds[0].trim()} curl -f http://localhost:8000/health -o /dev/null -w '%{http_code}' -s || echo '000'",
                                returnStdout: true
                            ).trim()

                            if (healthResponse != '200') {
                                error("Health endpoint returned HTTP ${healthResponse}")
                            }
                            echo "Health check passed - ${runningCount} replicas running"
                        } catch (Exception e) {
                            echo "Health check failed, retrying..."
                            sleep(time: 15, unit: 'SECONDS')
                            throw e
                        }
                    }
                }
            }
        }

        stage('Verify') {
            steps {
                sh """
                    cd ${COMPOSE_DIR}
                    docker compose -f ${env.COMPOSE_FILE} ps ${env.SERVICE_NAME}
                """
            }
        }

        stage('Cleanup Old Backups') {
            steps {
                script {
                    sh """
                        docker images | grep 'netgrader-backend-fastapi-backup-${env.ENV_NAME}' | awk '{print \$1\":\"\$2}' | sort -r | tail -n +6 | xargs -r docker rmi || true
                    """
                    sh 'docker image prune -f'
                }
            }
        }
    }

    post {
        success {
            echo "Backend FastAPI [${env.BRANCH_NAME}] deployed successfully. ${env.SCALE} replicas. Build #${env.BUILD_NUMBER}"
        }
        failure {
            script {
                echo "DEPLOYMENT FAILED - INITIATING ROLLBACK"
                if (env.BUILD_NUMBER.toInteger() > 1) {
                    try {
                        def backupExists = sh(script: "docker images -q ${env.PREVIOUS_IMAGE}", returnStdout: true).trim()
                        if (backupExists) {
                            sh """
                                docker tag ${env.PREVIOUS_IMAGE} ${env.IMAGE_NAME}
                                cd ${COMPOSE_DIR}
                                docker compose -f ${env.COMPOSE_FILE} down ${env.SERVICE_NAME}
                                docker compose -f ${env.COMPOSE_FILE} up -d --scale ${env.SERVICE_NAME}=${env.SCALE} ${env.SERVICE_NAME}
                            """
                            sleep(time: 20, unit: 'SECONDS')
                            echo "ROLLBACK SUCCESSFUL - restored to build #${env.BUILD_NUMBER.toInteger() - 1}"
                        } else {
                            echo "No backup found - cannot rollback"
                        }
                    } catch (Exception e) {
                        echo "ROLLBACK FAILED: ${e.message} - Manual intervention required"
                    }
                }
                sh """
                    cd ${COMPOSE_DIR}
                    docker compose -f ${env.COMPOSE_FILE} logs ${env.SERVICE_NAME} --tail=100 || true
                """
            }
        }
    }
}
