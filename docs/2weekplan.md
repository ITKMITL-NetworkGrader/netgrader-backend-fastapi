UPDATED 2-WEEK MVP/POC MILESTONES

  I've added Ubuntu service checking as a dedicated component. Here's the revised plan:

  ---
  MILESTONE 1: Single Test Type with Batfish (Days 1-5)

  Priority: CRITICAL - This is your demo

  Goal: Prove Batfish works with ONE test type (CONFIGURATION)

  Tasks (Ordered by Priority):

  1. Install Batfish (Day 1 - 2 hours)
    - pip install pybatfish
    - Start Batfish container/service
    - Test basic connection
  2. Create minimal telemetry structure (Day 1-2 - 6 hours)
  app/core/telemetry/
  ├── parsers/
  │   └── batfish_parser.py       # Parse Batfish results only
  └── schemas/
      └── configuration_schema.json  # ONE schema for config tests
  3. Build Batfish service (Day 2-3 - 8 hours)
 batfish_service.py
  # Core functions:
  # - collect_device_configs()
  # - create_snapshot()
  # - run_question(question_name)
  # - parse_to_netgrader_format()
  4. Create ONE configuration handler (Day 3-4 - 6 hours)
  app/services/test_handlers/configuration_handler.py
  # Test ONE thing: ACL
  5. Integration with existing flow (Day 4-5 - 6 hours)
    - Add test_type: "configuration_static" to your existing models
    - Route through Batfish handler instead of live testing
    - Return results in existing TestResult format
  6. Demo test case (Day 5 - 2 hours)
    - Create ONE lab scenario testing BGP config
    - Show: Static analysis finds config errors in <5 seconds
    - Compare: vs live testing taking 30+ seconds

  Deliverable: Working Batfish integration for configuration validation that's visibly
  faster/safer than live testing

  ---
  MILESTONE 2: Enhanced Parsing for Ubuntu Tests (Days 6-9)

  Priority: HIGH - Quick win, improves existing features

  Goal: Make Ubuntu SSH tests output structured data (ping + services)

  Tasks (Ordered by Priority):

  Part A: Ping Parsing (Days 6-7)

  1. Add parsing libraries (Day 6 - 1 hour)
    - pip install ttp textfsm
    - Create TTP template for ping output
  2. Create Ubuntu parser (Day 6-7 - 4 hours)
  app/core/telemetry/parsers/ubuntu_parser.py
  # parse_ping_output() → structured JSON
  3. Update Ubuntu connectivity tests (Day 7 - 4 hours)
    - Modify execute_ping_task() in nornir_grading_service.py:53-166
    - Add structured telemetry to results
    - Keep backward compatibility

  Part B: Service Status Parsing (Days 8-9) ⭐ NEW

  4. Add systemd JSON parsing (Day 8 - 3 hours)
  app/core/telemetry/parsers/ubuntu_parser.py
  # parse_systemd_status() → structured JSON
  # Uses: systemctl show --property=... (JSON output)
  5. Create service schema (Day 8 - 2 hours)
  app/core/telemetry/schemas/service_schema.json
  {
    "service_name": "nginx",
    "status": "active",
    "sub_state": "running",
    "enabled": true,
    "memory_current": 1234567,
    "restart_count": 0,
    "uptime_seconds": 86400
  }
  6. Enhance service_check template (Day 8-9 - 4 hours)
    - Modify existing service_check in simple_grading_service.py:409-411
    - Replace systemctl status with systemctl show --no-pager
    - Parse output to structured format
    - Support multiple checks: active, enabled, memory usage, restart count
  7. Create standardized output (Day 9 - 3 hours)
  {
    "test_type": "service.status",
    "telemetry": {
      "service_name": "nginx",
      "is_active": true,
      "is_enabled": true,
      "is_running": true,
      "uptime_seconds": 86400,
      "memory_mb": 45.2,
      "restart_count": 0,
      "main_pid": 1234
    },
    "raw_output": "..."
  }

  Deliverable: Both ping tests AND service checks return structured, parseable data
  with rich telemetry

  ---
  MILESTONE 3: Hybrid Test Example (Days 10-11)

  Priority: MEDIUM - Shows the vision

  Goal: ONE test that combines Batfish static + live verification

  Tasks (Ordered by Priority):

  1. Create hybrid orchestrator (Day 10 - 4 hours)
  app/services/test_handlers/hybrid_orchestrator.py
  # combine_results(static_result, live_result)
  # generate_confidence_score()
  2. Pick ONE hybrid test case (Day 10 - 3 hours)
    - Example: OSPF configuration
    - Static: Batfish validates OSPF config syntax
    - Live: Ubuntu SSH checks OSPF neighbor state
    - Combined: High confidence if both pass
  3. Implement test flow (Day 10-11 - 6 hours)
    - Add test_type: "protocol_hybrid"
    - Run Batfish check first (fast, safe)
    - Run live check second (reality verification)
    - Return combined result with confidence score
  4. Create comparison report (Day 11 - 2 hours)
  {
    "static_analysis": { "status": "passed", "time": 3s },
    "live_verification": { "status": "passed", "time": 25s },
    "confidence_score": 95,
    "cross_validation": "Both methods agree"
  }

  Deliverable: ONE working hybrid test showing static + live validation together

  ---
  MILESTONE 4: Simple DSL Example (Days 12-14)

  Priority: MEDIUM - Usability improvement

  Goal: Show how instructors would use the new abstractions

  Tasks (Ordered by Priority):

  1. Design simple YAML format (Day 12 - 3 hours)
  # Network device configuration test
  - test_name: "BGP Configuration Check"
    test_type: "configuration_static"
    batfish_question: "bgp_sessions"
    expected_sessions: 4
    points: 10

  # Ubuntu service test (NEW example)
  - test_name: "Web Server Running"
    test_type: "service_check"
    device: "ubuntu1"
    service: "nginx"
    checks:
      - is_active: true
      - is_enabled: true
      - uptime_minutes: ">= 1"
    points: 5
  2. Create YAML parser (Day 12-13 - 4 hours)
    - Parse YAML → NetworkTask format
    - Map to appropriate handler
    - Validate structure
  3. Convert TWO existing tests (Day 13 - 3 hours)
    - Network config test (Batfish example)
    - Ubuntu service test (systemd example) ⭐ NEW
    - Side-by-side comparison for demo
  4. Documentation (Day 14 - 4 hours)
    - Quick start guide
    - API comparison (old vs new)
    - Example test library (5-7 examples including service checks)

  Deliverable: Working YAML DSL that's 80% simpler than current approach

  ---
  2-WEEK CRITICAL PATH (Updated)

  Week 1:
  ├─ Mon-Wed: Batfish integration (BLOCKING for demo)
  ├─ Thu-Fri: Configuration handler + demo test
  │
  Week 2:
  ├─ Mon-Tue: Ubuntu ping parsing
  ├─ Wed: Ubuntu service parsing ⭐ NEW
  ├─ Thu: Hybrid orchestrator + example
  └─ Fri: DSL + documentation (including service examples)

  ---
  MVP SUCCESS CRITERIA (Updated Demo Flow)

  Demo #1: Static Configuration Analysis (5 min)

  - Run configuration test with Batfish
  - Show: 3 seconds vs 30+ seconds
  - Show: Found config errors WITHOUT touching devices
  - Show: Structured output instead of regex parsing

  Demo #2: Enhanced Ubuntu Testing (5 min) ⭐ EXPANDED

  Part A - Ping Tests:
  - Run existing ping test
  - Show: Old output (raw text) vs New output (structured JSON)
  - Show: Better grading precision with parsed metrics (latency, packet loss)

  Part B - Service Status Tests: ⭐ NEW
  - Run service check on nginx/apache
  - Show: Old output (systemctl status text) vs New output (structured JSON)
  - Show: Rich telemetry: uptime, memory usage, restart count, enabled status
  - Example: "Deduct points if service restarted >3 times" (not possible before)

  Demo #3: Hybrid Validation (5 min)

  - Run hybrid OSPF test
  - Show: Static analysis predicts behavior
  - Show: Live testing confirms reality
  - Show: Confidence score combining both

  Demo #4: Instructor Experience (3 min) ⭐ UPDATED

  - Show old test definitions (complex code)
  - Show new YAML DSL (simple, declarative)
  - Highlight examples:
    - Network config test (Batfish)
    - Service check test (Ubuntu) ⭐ NEW
    - Hybrid test (both)
  - Show: 80% reduction in complexity

  ---
  ENHANCED VALUE PROPOSITION

  With Ubuntu service checking added, you can now demonstrate:

  Before (Current System):

  # Check if nginx is running - only gets text output
  command: "systemctl status nginx"
  # Grading: regex matching "active (running)" - fragile!

  After (MVP System):

  test_name: "Web Server Health Check"
  service: "nginx"
  checks:
    - is_active: true        # Service running
    - is_enabled: true       # Starts on boot
    - uptime_minutes: ">= 5" # Been running 5+ minutes
    - restart_count: "< 3"   # Hasn't crashed
    - memory_mb: "< 500"     # Not leaking memory
  points: 10

  // Structured output
  {
    "telemetry": {
      "is_active": true,
      "is_enabled": true,
      "uptime_seconds": 450,
      "restart_count": 0,
      "memory_mb": 42.3,
      "main_pid": 1234
    }
  }

  Why This Matters:

  - More sophisticated grading: Can check uptime, memory usage, restart count
  - Better student feedback: "Service crashed 5 times" vs "Service not running"
  - Industry standard format: Uses systemd's native structured output
  - Easier to write tests: Declarative checks vs regex parsing

  ---
  WHAT TO SKIP FOR MVP (Updated)

  DO NOT BUILD:
  - PyATS integration (save for later)
  - NTC-Templates (save for later)
  - Full schema library (only configuration_schema.json + service_schema.json)
  - Multiple Batfish question types (just ONE: BGP or OSPF)
  - Advanced service checks (journalctl logs, performance metrics)
  - Migration tooling (not needed for POC)
  - Backward compatibility layers (break things if needed)
  - Large test template library (just 2-3 examples)

  ---
  IMMEDIATE NEXT STEPS (Start Today)

  Hour 1: Install pybatfish, start Batfish service
  Hour 2: Create app/core/telemetry/ directory structureHour 3: Write
  batfish_service.py skeleton
  Hour 4: Test basic Batfish snapshot creation
  Day 2: Build configuration handler
  Day 3: Demo test working end-to-end
  Day 8: Add systemd structured parsing ⭐ NEW

  ---
  The Ubuntu service checking addition strengthens Milestone 2 by showing improvement
  across BOTH connectivity tests (ping) AND service validation. This makes the
  "enhanced Ubuntu testing" demo more compelling because you're improving multiple test
   types, not just one.