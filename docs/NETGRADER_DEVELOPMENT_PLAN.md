# NetGrader Development Plan - Hybrid Testing Framework Evolution

## Strategic Development Direction

### Core Architecture Evolution: Hybrid Testing Framework

**Current State:** Low-level Nornir + Paramiko + NAPALM DSL requiring deep network knowledge
**Target State:** High-level abstraction layer with hybrid static analysis (Batfish) + live testing

## Phase 1: Foundation Layer (Weeks 1-2)

### 1.1 Enhanced Tool Stack Integration

```bash
# New dependencies to add
pip install pyats[full] ntc-templates ttp pybatfish
```

### 1.2 Core Architecture Components

```
app/core/
├── telemetry/
│   ├── parsers/
│   │   ├── base_parser.py          # Abstract parser interface
│   │   ├── pyats_parser.py         # PyATS Genie integration
│   │   ├── ntc_parser.py           # NTC-Templates + TextFSM
│   │   ├── ubuntu_parser.py        # Ubuntu-specific parsing
│   │   └── batfish_parser.py       # Batfish result processing
│   ├── collectors/
│   │   ├── telemetry_collector.py  # Unified data collection
│   │   ├── config_collector.py     # Device configuration collection
│   │   └── schema_normalizer.py    # Output standardization
│   └── schemas/
│       ├── netgrader_standard.json # NetGrader standardized format
│       ├── connectivity_schema.json
│       ├── protocol_schema.json
│       ├── configuration_schema.json
│       ├── security_schema.json
│       └── service_schema.json
```

### 1.3 Two-Layer Data Strategy

- **Layer 1:** Use industry standards (NAPALM, PyATS, systemd JSON, ip command JSON)
- **Layer 2:** Aggregate into NetGrader-specific grading format optimized for scoring logic

## Phase 2: Test Type Handlers (Weeks 3-4)

### 2.1 Abstracted Test Handler Architecture

```
app/services/test_handlers/
├── base_handler.py                 # Abstract test handler interface
├── live_handlers/                  # Keep existing SSH-based approach
│   ├── connectivity_handler.py     # Ubuntu SSH + ping tests
│   └── service_handler.py          # Ubuntu service checks
├── static_handlers/                # NEW: Batfish-based handlers
│   ├── configuration_handler.py    # Config compliance (pure Batfish)
│   ├── protocol_handler.py         # Routing verification (Batfish)
│   └── security_handler.py         # ACL/policy analysis (Batfish)
└── hybrid_orchestrator.py          # Combines live + static results
```

### 2.2 Test Type Mapping Strategy

| Test Type     | Primary Method           | Enhancement                       |
|---------------|--------------------------|-----------------------------------|
| CONNECTIVITY  | Live (Ubuntu SSH + ping) | + Batfish reachability analysis   |
| PROTOCOL      | Live (show commands)     | + Batfish configuration analysis  |
| CONFIGURATION | Pure Batfish             | Static analysis only              |
| SECURITY      | Live (basic tests)       | + Batfish ACL/policy verification |
| SERVICE       | Live (Ubuntu SSH)        | Keep current approach             |

## Phase 3: Batfish Integration (Weeks 5-6)

### 3.1 Batfish Service Layer

```python
# app/services/batfish_service.py
class BatfishGradingService:
    # Configuration collection from devices
    # Snapshot creation and management
    # Built-in question execution
    # Custom question development
    # Result parsing and grading
```

### 3.2 Key Batfish Integration Points

- **Configuration Collection:** Automated show running-config collection
- **Snapshot Management:** Per-lab isolated analysis environments
- **Question Mapping:** 100+ built-in questions → NetGrader test types
- **Cross-validation:** Compare static predictions with live results

## Phase 4: Enhanced DSL & Abstractions (Weeks 7-8)

### 4.1 High-Level Test Definitions

```yaml
# Instead of low-level commands, instructors write:
comprehensive_network_test:
  test_type: "hybrid"
  description: "Complete network verification"

  static_analysis:                  # Batfish tests
    - question: "bgp_sessions"
      expected_sessions: 4
      points: 10
    - question: "acl_behavior"
      test_flows: [...]
      points: 15

  live_testing:                     # Keep current Ubuntu approach
    - ubuntu_ping:
        source: "ubuntu1"
        target: "8.8.8.8"
        points: 5
    - service_check:
        device: "ubuntu1"
        service: "nginx"
        points: 5
```

### 4.2 Standardized Output Format

```json
{
    "test_execution": {...},
    "grading_data": {
        "total_points": 30,
        "earned_points": 25,
        "test_cases": [...],
        "overall_status": "PASSED"
    },
    "telemetry_summary": {
        "source_standards": ["batfish", "napalm", "systemd"],
        "key_metrics": {...},
        "quality_score": 95,
        "cross_validation": {...}
    },
    "raw_data_references": {...}
}
```

## Phase 5: Migration Strategy (Weeks 9-10)

### 5.1 Backward Compatibility

- Keep existing Nornir-based custom task system
- Add new handlers as additional options
- Gradual migration of built-in templates

### 5.2 Ubuntu Testing Enhancement

```python
# Enhanced Ubuntu testing with telemetry
ubuntu_result = await self.ubuntu_collector.execute_ping(...)
parsed_telemetry = await self.ubuntu_parser.parse_ping_output(...)

# Standardized result
structured_result = {
    "test_type": "connectivity.ping",
    "telemetry": {
        "reachable": True,
        "avg_latency_ms": 15.2,
        "packet_loss_percent": 0
    },
    "raw_output": ubuntu_result.stdout
}
```

## Development Priorities & Benefits

### Immediate Benefits (Phase 1-2)

1. **Better Data Quality:** Structured parsing instead of regex hell
2. **Vendor Agnostic:** Same tests work across Cisco, Juniper, Arista
3. **Standardized Output:** Consistent JSON schemas for all test types

### Medium-term Benefits (Phase 3-4)

1. **Safety:** Static analysis without touching live networks
2. **Speed:** 3 orders of magnitude faster than live testing
3. **Comprehensive Coverage:** Both configuration compliance AND live verification

### Long-term Benefits (Phase 5+)

1. **Developer Experience:** High-level abstractions vs low-level commands
2. **Extensibility:** Easy to add new test types and parsers
3. **Cross-validation:** Static predictions vs live results for confidence scoring

## Key Implementation Decisions

### 1. Keep Ubuntu SSH Approach

- Your current Ubuntu SSH testing works well
- Enhance with better parsing and telemetry
- Don't change what's working

### 2. Add Batfish for Network Devices

- Perfect for CONFIGURATION, PROTOCOL, SECURITY test types
- Provides static analysis capabilities you currently lack
- Complements rather than replaces live testing

### 3. Two-Layer Data Architecture

- **Layer 1:** Industry standards (NAPALM, PyATS, Batfish, systemd)
- **Layer 2:** NetGrader grading format optimized for scoring logic
- Best of both worlds: reliability + grading optimization

### 4. Hybrid Testing Strategy

- Static analysis for safety and speed
- Live testing for reality verification
- Cross-validation for confidence scoring

## Success Metrics

1. **Instructor Experience:** Reduce test creation complexity by 80%
2. **Student Experience:** More comprehensive and faster feedback
3. **System Reliability:** Higher confidence through cross-validation
4. **Maintainability:** Cleaner abstractions, easier to extend
5. **Performance:** Faster grading through static analysis

## Tools & Technologies Stack

### Core Technologies
- **Batfish:** Static network analysis and configuration validation
- **PyATS/Genie:** 800+ network device parsers (Cisco, Juniper, Arista, etc.)
- **NTC-Templates:** Community TextFSM templates for network output parsing
- **TTP:** Template Text Parser for flexible output processing

### Industry Standards Integration
- **NAPALM:** Cross-vendor network device abstraction
- **systemd JSON:** Ubuntu service status in structured format
- **ip command JSON:** Linux networking information parsing

### Current Stack (Enhanced)
- **Nornir:** Task orchestration framework (keep existing)
- **Paramiko:** SSH connectivity (enhance with better parsing)
- **FastAPI:** REST API framework (current)

## Next Steps for Implementation

When ready to begin implementation:

1. **Start with Phase 1:** Set up the foundation layer and telemetry architecture
2. **Proof of Concept:** Implement one Batfish integration for CONFIGURATION test type
3. **Ubuntu Enhancement:** Add structured parsing to existing SSH-based tests
4. **Gradual Migration:** Test with existing lab assignments before full rollout
5. **Documentation:** Update instructor guides for new high-level DSL

---

*This development plan transforms NetGrader from a low-level automation tool into a high-level network testing platform while maintaining the reliability and flexibility of your current Ubuntu SSH approach.*

**Plan Created:** September 19, 2025
**Status:** Ready for Implementation
**Estimated Timeline:** 10 weeks for full implementation