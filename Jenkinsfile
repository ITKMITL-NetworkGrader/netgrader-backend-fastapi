pipeline {
    agent any
    
    triggers {
        pollSCM('* * * * *')  // Poll GitHub every minute
    }
    
    environment {
        BACKEND_DIR = '/home/netgrader/netgrader/netgrader-backend-fastapi'
        COMPOSE_DIR = '/home/netgrader/netgrader/netgrader-container'
        SERVICE_NAME = 'backend-fastapi'
        BACKUP_IMAGE = "netgrader-backend-fastapi-backup-${BUILD_NUMBER}"
        PREVIOUS_IMAGE = "netgrader-backend-fastapi-backup-${BUILD_NUMBER - 1}"
        REPLICAS = '8'  // Number of replicas from docker-compose.yml
    }
    
    stages {
        stage('Backup Current Image') {
            steps {
                script {
                    echo "[BACKUP] Creating backup of current image..."
                    sh """
                        docker tag netgrader-container-backend-fastapi:latest ${BACKUP_IMAGE} || echo "No existing image to backup"
                    """
                }
            }
        }
        
        stage('Pull Latest Code') {
            steps {
                script {
                    echo "[GIT] Updating ${BACKEND_DIR}..."
                    sh """
                        sudo -u netgrader bash -c 'cd ${BACKEND_DIR} && git reset --hard HEAD && git pull origin main'
                    """
                }
            }
        }
        
        stage('Check Environment File') {
            steps {
                script {
                    echo "[CHECK] Verifying .env file exists..."
                    sh """
                        sudo -u netgrader test -f ${BACKEND_DIR}/.env && echo '✅ Environment file exists' || exit 1
                    """
                }
            }
        }
        
        stage('Build Docker Image') {
            steps {
                script {
                    echo "[DOCKER] Building ${SERVICE_NAME} image..."
                    
                    // Build with error checking
                    def buildResult = sh(
                        script: """
                            sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose build ${SERVICE_NAME}'
                        """,
                        returnStatus: true
                    )
                    
                    if (buildResult != 0) {
                        error("❌ Docker build failed with exit code ${buildResult}")
                    }
                    
                    echo "✅ Docker build completed successfully"
                }
            }
        }
        
        stage('Verify Build Output') {
            steps {
                script {
                    echo "[VERIFY] Checking if build created valid image..."
                    
                    // Check if image was created
                    def imageExists = sh(
                        script: "docker images netgrader-container-backend-fastapi:latest -q",
                        returnStdout: true
                    ).trim()
                    
                    if (!imageExists) {
                        error("❌ Build did not produce a valid image!")
                    }
                    
                    // Check image size (sanity check)
                    def imageSize = sh(
                        script: "docker images netgrader-container-backend-fastapi:latest --format '{{.Size}}'",
                        returnStdout: true
                    ).trim()
                    
                    echo "✅ Image created successfully - Size: ${imageSize}"
                }
            }
        }
        
        stage('Scale Down Replicas') {
            steps {
                script {
                    echo "[DOCKER] Scaling down ${SERVICE_NAME} replicas gracefully..."
                    sh """
                        sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose down ${SERVICE_NAME}'
                    """
                }
            }
        }
        
        stage('Deploy Backend FastAPI') {
            steps {
                script {
                    echo "[DOCKER] Starting ${SERVICE_NAME} with ${REPLICAS} replicas..."
                    sh """
                        sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose up -d --scale ${SERVICE_NAME}=${REPLICAS} ${SERVICE_NAME}'
                    """
                }
            }
        }
        
        stage('Wait for Startup') {
            steps {
                script {
                    echo "[HEALTH] Waiting for replicas to start..."
                    sleep(time: 20, unit: 'SECONDS')
                }
            }
        }
        
        stage('Health Check Replicas') {
            steps {
                script {
                    echo "[HEALTH] Checking health of all replicas..."
                    
                    def healthCheckPassed = false
                    def attempts = 0
                    def maxAttempts = 6
                    
                    retry(maxAttempts) {
                        attempts++
                        echo "Health check attempt ${attempts}/${maxAttempts}..."
                        
                        try {
                            // Count running containers
                            def runningCount = sh(
                                script: """
                                    sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose ps ${SERVICE_NAME}' | grep -c "Up" || echo "0"
                                """,
                                returnStdout: true
                            ).trim().toInteger()
                            
                            echo "Running replicas: ${runningCount}/${REPLICAS}"
                            
                            if (runningCount < REPLICAS.toInteger()) {
                                error("Only ${runningCount}/${REPLICAS} replicas are running")
                            }
                            
                            // Check one replica's health endpoint (assuming it has /health)
                            def healthResponse = sh(
                                script: """
                                    curl -f http://localhost:8000/health -o /dev/null -w '%{http_code}' -s || echo "000"
                                """,
                                returnStdout: true
                            ).trim()
                            
                            echo "Health endpoint response: ${healthResponse}"
                            
                            if (healthResponse != "200") {
                                error("Health endpoint returned HTTP ${healthResponse}")
                            }
                            
                            // Check logs for errors in any replica
                            def logs = sh(
                                script: """
                                    sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose logs ${SERVICE_NAME} --tail=100'
                                """,
                                returnStdout: true
                            )
                            
                            if (logs.contains("ERROR") || logs.contains("Error:") || logs.contains("FATAL") || logs.contains("Traceback")) {
                                echo "⚠️ WARNING: Errors found in logs:"
                                echo logs.take(500)  // Show first 500 chars
                                // Note: Don't fail here as some errors might be old logs
                            }
                            
                            healthCheckPassed = true
                            echo "✅ All ${REPLICAS} replicas are healthy"
                            
                        } catch (Exception e) {
                            echo "⚠️ Health check failed: ${e.message}"
                            if (attempts < maxAttempts) {
                                echo "Retrying in 10 seconds..."
                                sleep(time: 10, unit: 'SECONDS')
                            }
                            throw e
                        }
                    }
                    
                    if (!healthCheckPassed) {
                        error("❌ Health check failed after ${maxAttempts} attempts")
                    }
                }
            }
        }
        
        stage('Verify Deployment') {
            steps {
                script {
                    echo "[DOCKER] Verifying all ${SERVICE_NAME} replicas are running..."
                    sh """
                        sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose ps ${SERVICE_NAME}'
                    """
                }
            }
        }
        
        stage('Cleanup Old Backups') {
            steps {
                script {
                    echo "[CLEANUP] Keeping last 5 backups, removing older ones..."
                    sh """
                        docker images | grep 'netgrader-backend-fastapi-backup' | awk '{print \$1\":\"\$2}' | sort -r | tail -n +6 | xargs -r docker rmi || echo "No old backups to clean"
                    """
                    echo "[CLEANUP] Cleaning up unused images..."
                    sh 'docker image prune -f'
                }
            }
        }
    }
    
    post {
        success {
            echo "=========================================="
            echo "✅ Backend FastAPI deployed successfully!"
            echo "Build #${BUILD_NUMBER} - ${REPLICAS} replicas running"
            echo "Backup: ${BACKUP_IMAGE}"
            echo "=========================================="
        }
        failure {
            echo "=========================================="
            echo "❌ DEPLOYMENT FAILED - INITIATING ROLLBACK"
            echo "=========================================="
            script {
                def rollbackSuccess = false
                
                if (BUILD_NUMBER.toInteger() > 1) {
                    echo "🔄 Rolling back to Build #${BUILD_NUMBER - 1}..."
                    echo "Previous backup image: ${PREVIOUS_IMAGE}"
                    
                    try {
                        // Verify previous backup exists
                        def backupExists = sh(
                            script: "docker images -q ${PREVIOUS_IMAGE}",
                            returnStdout: true
                        ).trim()
                        
                        if (!backupExists) {
                            echo "⚠️  WARNING: Previous backup image not found!"
                            echo "Cannot rollback - this was likely the first build"
                        } else {
                            // Perform rollback
                            sh """
                                echo "Tagging previous image as latest..."
                                docker tag ${PREVIOUS_IMAGE} netgrader-container-backend-fastapi:latest
                                
                                echo "Restarting service with previous version..."
                                sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose down ${SERVICE_NAME}'
                                sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose up -d --scale ${SERVICE_NAME}=${REPLICAS} ${SERVICE_NAME}'
                            """
                            
                            // Verify rollback worked
                            sleep(time: 20, unit: 'SECONDS')
                            
                            def runningCount = sh(
                                script: """
                                    sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose ps ${SERVICE_NAME}' | grep -c "Up" || echo "0"
                                """,
                                returnStdout: true
                            ).trim().toInteger()
                            
                            if (runningCount >= REPLICAS.toInteger()) {
                                rollbackSuccess = true
                                echo "=========================================="
                                echo "✅ ROLLBACK SUCCESSFUL"
                                echo "Service restored to Build #${BUILD_NUMBER - 1}"
                                echo "${runningCount} replicas running"
                                echo "=========================================="
                            } else {
                                echo "⚠️  WARNING: Only ${runningCount}/${REPLICAS} replicas started after rollback"
                            }
                        }
                    } catch (Exception e) {
                        echo "=========================================="
                        echo "❌ ROLLBACK FAILED: ${e.message}"
                        echo "Manual intervention required!"
                        echo "=========================================="
                    }
                } else {
                    echo "⚠️  This is Build #1 - no previous version to rollback to"
                }
                
                // Show logs to help diagnose the issue
                echo ""
                echo "=========================================="
                echo "Container logs (last 100 lines):"
                echo "=========================================="
                sh """
                    sudo -u netgrader bash -c 'cd ${COMPOSE_DIR} && docker compose logs ${SERVICE_NAME} --tail=100' || echo "Could not fetch logs"
                """
                
                if (!rollbackSuccess && BUILD_NUMBER.toInteger() > 1) {
                    echo ""
                    echo "⚠️  SERVICE MAY BE DOWN - Manual rollback required"
                }
            }
        }
    }
}