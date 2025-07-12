#!/usr/bin/env python3
"""
Mock ElysiaJS callback server for testing real-time feedback
"""
from fastapi import FastAPI, Request
import uvicorn
import json

app = FastAPI(title="Mock ElysiaJS Callback Server")

@app.post("/api/grading-callbacks/started")
async def job_started(request: Request):
    """Receive job started notification"""
    data = await request.json()
    print(f"🚀 Job Started: {json.dumps(data, indent=2)}")
    return {"status": "received"}

@app.post("/api/grading-callbacks/progress")
async def progress_update(request: Request):
    """Receive progress updates"""
    data = await request.json()
    progress = data.get('percentage', 0)
    message = data.get('message', '')
    job_id = data.get('job_id', '')
    current_test = data.get('current_test', '')
    
    print(f"📊 Progress Update [{job_id}]: {progress:.1f}% - {message}")
    if current_test:
        print(f"   🔍 Current Test: {current_test}")
    
    return {"status": "received"}

@app.post("/api/grading-callbacks/result")
async def final_result(request: Request):
    """Receive final grading result"""
    data = await request.json()
    job_id = data.get('job_id', '')
    status = data.get('status', '')
    points_earned = data.get('total_points_earned', 0)
    points_possible = data.get('total_points_possible', 0)
    
    print(f"🎯 Final Result [{job_id}]:")
    print(f"   Status: {status}")
    print(f"   Score: {points_earned}/{points_possible}")
    print(f"   Tests: {len(data.get('test_results', []))}")
    
    # Print individual test results
    for test_result in data.get('test_results', []):
        test_id = test_result.get('test_id', '')
        test_status = test_result.get('status', '')
        test_message = test_result.get('message', '')
        test_points = test_result.get('points_earned', 0)
        test_possible = test_result.get('points_possible', 0)
        
        status_emoji = "✅" if test_status == "passed" else "❌"
        print(f"   {status_emoji} {test_id}: {test_message} ({test_points}/{test_possible} pts)")
    
    return {"status": "received"}

@app.get("/")
def root():
    return {
        "message": "Mock ElysiaJS Callback Server",
        "status": "running",
        "endpoints": [
            "/api/grading-callbacks/started",
            "/api/grading-callbacks/progress", 
            "/api/grading-callbacks/result"
        ]
    }

if __name__ == "__main__":
    print("🎭 Starting Mock ElysiaJS Callback Server...")
    print("📡 Listening for callbacks from NetGrader Worker")
    print("🌐 Server: http://localhost:3000")
    print("-" * 50)
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3000,
        log_level="info"
    )
