"""
Advanced scoring service that compares extracted data against test cases
"""

import re
import json
import logging
from typing import Any, Dict, List, Union
from app.schemas.models import TestCase, TestCaseResult, NetworkTask, TaskGroup, TestResult, GroupResult
from app.services.grading.ipv6_utils import compare_ipv6, is_link_local, is_valid_ipv6, compare_link_local

logger = logging.getLogger(__name__)

class ScoringService:
    """Service for evaluating test results against detailed test cases"""
    
    def evaluate_test_cases_for_task(self, task: NetworkTask, extracted_data: Dict[str, Any]) -> List[TestCaseResult]:
        """
        Evaluate all test cases for a network task against extracted data
        
        Args:
            task: The network task with test cases
            extracted_data: Data extracted from the device/task output
            
        Returns:
            List of test case results with scoring
        """
        results = []
        
        for test_case in task.test_cases:
            result = self._evaluate_single_test_case(test_case, extracted_data)
            results.append(result)
            
        return results
    
    def _evaluate_single_test_case(self, test_case: TestCase, extracted_data: Dict[str, Any]) -> TestCaseResult:
        """Evaluate a single test case against extracted data using CLAUDE.md format"""
        
        # Extract the actual value using the flexible extraction method
        actual_value = self._extract_value_from_data(extracted_data, test_case.comparison_type)
        # Perform comparison based on type
        passed, message = self._compare_values(
            actual_value, 
            test_case.expected_result, 
            test_case.comparison_type
        )
        
        # Default to 1 point per test case
        points_earned = 1 if passed else 0
        
        return TestCaseResult(
            description=f"{test_case.comparison_type} check",
            expected_value=test_case.expected_result,
            actual_value=actual_value,
            comparison_type=test_case.comparison_type,
            status="passed" if passed else "failed",
            points_earned=points_earned,
            points_possible=1,
            message=message
        )
    
    def _extract_value_from_data(self, data: Dict[str, Any], key_path: str) -> Any:
        """
        Extract value from nested data structure using dot notation or direct key
        Handles special comparison types intelligently
        
        Examples:
            - "interface_status" -> data["interface_status"]
            - "interfaces.GigabitEthernet0/0.ip" -> data["interfaces"]["GigabitEthernet0/0"]["ip"]
            - "ping_stats.success_rate" -> data["ping_stats"]["success_rate"]
            - "success" -> data.get('success') or data.get('status') == 'passed'
        """
        try:
            # Handle special comparison types with intelligent extraction
            if key_path == "success":
                # Check both success field and status field from CLAUDE.md format
                return data.get('success', False) or data.get('status') == 'passed'
            elif key_path == "ssh_success":
                return data.get('ssh_success', False) or data.get('success', False)
            elif key_path == "equals":
                # For equals, check for specific values at root level first
                if 'actual_ip' in data:
                    return data['actual_ip']
                elif 'match' in data:
                    return data['match']
                # Check custom fields as fallback
                custom = data.get('custom', {})
                if 'actual_ip' in custom:
                    return custom['actual_ip']
                elif 'match' in custom:
                    return custom['match']
                # Final fallback to stdout or status
                return data.get('stdout', '') or data.get('status', '')
            
            # First try to find the value at root level
            if "." not in key_path and key_path in data:
                return data[key_path]
                
            # Then try custom fields as fallback (CLAUDE.md nested format)
            custom = data.get('custom', {})
            if key_path in custom:
                return custom[key_path]
            
            # Handle direct key access (for keys not found above)
            if "." not in key_path:
                return data.get(key_path)
            
            # Handle nested key access
            keys = key_path.split(".")
            current = data
            
            for key in keys:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    return None
                    
                if current is None:
                    return None
                    
            return current
            
        except Exception as e:
            logger.warning(f"Failed to extract value for key '{key_path}': {e}")
            return None
    
    def _compare_values(self, actual: Any, expected: Any, comparison_type: str) -> tuple[bool, str]:
        """
        Compare actual vs expected values based on comparison type
        
        Returns:
            (passed: bool, message: str)
        """
        try:
            if comparison_type == "equals":
                try:
                    passed = int(actual) == int(expected)
                    message = f"Expected: {expected}, Got: {actual}"
                except (ValueError, TypeError):
                    passed = str(actual) == str(expected)
                    message = f"Expected: {expected}, Got: {actual}"
                
            elif comparison_type == "contains":
                if isinstance(actual, str) and isinstance(expected, str):
                    passed = expected.lower() in actual.lower()
                    message = f"Expected '{expected}' to be contained in '{actual}'"
                elif isinstance(actual, (list, tuple)):
                    passed = expected in actual
                    message = f"Expected '{expected}' to be in list {actual}"
                else:
                    passed = False
                    message = f"Cannot check containment: actual={actual}, expected={expected}"
                    
            elif comparison_type == "regex":
                if isinstance(actual, str) and isinstance(expected, str):
                    passed = bool(re.search(expected, actual, re.IGNORECASE))
                    message = f"Expected pattern '{expected}' {'found' if passed else 'not found'} in '{actual}'"
                else:
                    passed = False
                    message = f"Regex comparison requires strings: actual={type(actual)}, expected={type(expected)}"
                    
            elif comparison_type == "range":
                if isinstance(expected, dict) and "min" in expected and "max" in expected:
                    try:
                        actual_num = float(actual)
                        passed = expected["min"] <= actual_num <= expected["max"]
                        message = f"Expected {actual_num} to be between {expected['min']} and {expected['max']}"
                    except (ValueError, TypeError):
                        passed = False
                        message = f"Cannot convert '{actual}' to number for range comparison"
                else:
                    passed = False
                    message = f"Range comparison requires min/max dict, got: {expected}"
                    
            elif comparison_type == "exists":
                passed = actual is not None and actual != ""
                message = f"Expected value to exist, got: {actual}"
                
            elif comparison_type == "not_exists":
                passed = actual is None or actual == ""
                message = f"Expected value to not exist, got: {actual}"
                
            elif comparison_type == "greater_than":
                try:
                    passed = float(actual) > float(expected)
                    message = f"Expected {actual} > {expected}"
                except (ValueError, TypeError):
                    passed = False
                    message = f"Cannot compare '{actual}' > '{expected}' (not numbers)"
                    
            elif comparison_type == "less_than":
                try:
                    passed = float(actual) < float(expected)
                    message = f"Expected {actual} < {expected}"
                except (ValueError, TypeError):
                    passed = False
                    message = f"Cannot compare '{actual}' < '{expected}' (not numbers)"
                    
            elif comparison_type == "count":
                if isinstance(actual, (list, tuple, str)):
                    actual_count = len(actual)
                    passed = actual_count == expected
                    message = f"Expected count {expected}, got {actual_count}"
                else:
                    passed = False
                    message = f"Cannot count items in {type(actual)}"
            
            elif comparison_type == "success":
                # Expected should be boolean
                passed = bool(actual) == bool(expected)
                message = f"Expected success: {expected}, Got: {actual}"
                
            elif comparison_type == "ssh_success":
                # Expected should be boolean
                passed = bool(actual) == bool(expected)
                message = f"Expected SSH success: {expected}, Got: {actual}"
            
            elif comparison_type == "ipv6_equals":
                # IPv6 address comparison (handles compressed and full forms)
                passed = compare_ipv6(str(actual), str(expected))
                if passed:
                    message = f"IPv6 addresses match: {actual} == {expected}"
                else:
                    message = f"IPv6 addresses don't match: Expected {expected}, Got: {actual}"
            
            elif comparison_type == "ipv6_link_local":
                # Check if address is a link-local IPv6 address (fe80::/10)
                expect_link_local = bool(expected) if expected is not None else True
                passed, message = compare_link_local(str(actual), expect_link_local)
            
            elif comparison_type == "ipv6_valid":
                # Check if the value is a valid IPv6 address
                passed = is_valid_ipv6(str(actual))
                message = f"IPv6 validation: {actual} is {'valid' if passed else 'invalid'}"
                    
            else:
                passed = False
                message = f"Unknown comparison type: {comparison_type}"
                
        except Exception as e:
            passed = False
            message = f"Comparison error: {str(e)}"
            
        return passed, message
    
    def calculate_test_score(self, test_case_results: List[TestCaseResult], total_points: int) -> tuple[int, str]:
        """
        Calculate overall test score from test case results
        
        Returns:
            (points_earned, summary_message)
        """
        if not test_case_results:
            return 0, "No test cases defined"
        
        total_case_points = sum(result.points_possible for result in test_case_results)
        earned_case_points = sum(result.points_earned for result in test_case_results)
        
        # Calculate proportional score
        if total_case_points > 0:
            score_ratio = earned_case_points / total_case_points
            final_points = int(total_points * score_ratio)
        else:
            final_points = 0
            
        passed_cases = sum(1 for result in test_case_results if result.status == "passed")
        total_cases = len(test_case_results)
        
        summary = f"Passed {passed_cases}/{total_cases} test cases ({final_points}/{total_points} points)"
        
        return final_points, summary
    
    def evaluate_task_group(self, group: TaskGroup, task_results: List[TestResult]) -> GroupResult:
        """
        Evaluate a task group using all-or-nothing or proportional scoring
        
        Args:
            group: The task group configuration
            task_results: Results from all tasks in the group
            
        Returns:
            GroupResult with group-level scoring
        """
        if not task_results:
            return GroupResult(
                group_id=group.group_id,
                title=group.title,
                status="error",
                group_type=group.group_type,
                points_earned=0,
                points_possible=group.points,
                execution_time=0.0,
                task_results=[],
                message="No task results provided for group"
            )
        
        total_execution_time = sum(result.execution_time for result in task_results)
        
        if group.group_type == "all_or_nothing":
            return self._evaluate_all_or_nothing_group(group, task_results, total_execution_time)
        elif group.group_type == "proportional":
            return self._evaluate_proportional_group(group, task_results, total_execution_time)
        else:
            logger.error(f"Unknown group_type: {group.group_type}")
            return GroupResult(
                group_id=group.group_id,
                title=group.title,
                status="error",
                group_type=group.group_type,
                points_earned=0,
                points_possible=group.points,
                execution_time=total_execution_time,
                task_results=task_results,
                message=f"Unknown group type: {group.group_type}"
            )
    
    def _evaluate_all_or_nothing_group(self, group: TaskGroup, task_results: List[TestResult], 
                                     total_execution_time: float) -> GroupResult:
        """Evaluate group with all-or-nothing scoring"""
        
        # Check if all tasks passed
        all_passed = all(result.status == "passed" for result in task_results)
        failed_tasks = [result for result in task_results if result.status != "passed"]
        
        if all_passed:
            points_earned = group.points
            status = "passed"
            message = f"Group passed: all {len(task_results)} tasks succeeded"
        else:
            points_earned = 0
            status = "failed"
            failed_count = len(failed_tasks)
            failed_names = [result.test_name for result in failed_tasks]
            message = f"Group failed: {failed_count}/{len(task_results)} tasks failed ({', '.join(failed_names)})"
        
        return GroupResult(
            group_id=group.group_id,
            title=group.title,
            status=status,
            group_type=group.group_type,
            points_earned=points_earned,
            points_possible=group.points,
            execution_time=total_execution_time,
            task_results=task_results,
            message=message
        )
    
    def _evaluate_proportional_group(self, group: TaskGroup, task_results: List[TestResult], 
                                   total_execution_time: float) -> GroupResult:
        """Evaluate group with proportional scoring"""
        
        passed_tasks = [result for result in task_results if result.status == "passed"]
        passed_count = len(passed_tasks)
        total_count = len(task_results)
        
        if total_count > 0:
            score_ratio = passed_count / total_count
            points_earned = int(group.points * score_ratio)
        else:
            score_ratio = 0
            points_earned = 0
        
        # Determine status
        if passed_count == total_count:
            status = "passed"
            message = f"Group fully passed: {passed_count}/{total_count} tasks succeeded"
        elif passed_count > 0:
            status = "partial"
            message = f"Group partially passed: {passed_count}/{total_count} tasks succeeded ({points_earned}/{group.points} points)"
        else:
            status = "failed" 
            message = f"Group failed: 0/{total_count} tasks succeeded"
        
        return GroupResult(
            group_id=group.group_id,
            title=group.title,
            status=status,
            group_type=group.group_type,
            points_earned=points_earned,
            points_possible=group.points,
            execution_time=total_execution_time,
            task_results=task_results,
            message=message
        )

    def group_tasks_by_id(self, tasks: List[NetworkTask]) -> Dict[str, List[NetworkTask]]:
        """
        Group tasks by their group_id
        
        Returns:
            Dictionary with group_id as key and list of tasks as value
            Tasks without group_id are not included
        """
        grouped_tasks = {}
        
        for task in tasks:
            if task.group_id:
                grouped_tasks.setdefault(task.group_id, []).append(task)

        return grouped_tasks

    def get_ungrouped_tasks(self, tasks: List[NetworkTask]) -> List[NetworkTask]:
        """
        Get tasks that don't belong to any group
        
        Returns:
            List of tasks without group_id
        """
        return [task for task in tasks if not task.group_id]