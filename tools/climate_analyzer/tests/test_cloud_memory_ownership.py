import unittest
from copy import deepcopy
from epw_climate_analyzer.cloud_memory_ownership import summarize_ownership as report

def fixture():
    return {"memory":{"used":2705420288,"limit":3221225472,"anonymous":1796468736},
            "container_processes":{"status":"sampled","limited":False,"read_errors":0,"processes":[
              {"pid":3298,"app":True,"category":"Python","rss_anon":1193123840,"pss_anon":1193123840},
              {"pid":3023,"app":False,"category":"Python","argv_classification":"classified","climate_app_target":True,
               "rss_anon":576933888,"pss_anon":576933888,"parent_pid":1,"sockets":{"status":"sampled","tcp_listen_ports":[],"tcp_established":0,"tcp_other":1,"tcp_states":{"CLOSE_WAIT":1}}}]},
            "allocator":{"status":"sampled","arena_setting_origin":"no explicit exec arena limit observed","arena_max_exec_env":None,
            "arena_tunable_exec":None,"arena_max_env":None,"free_arena_bytes":637268560},
            "shared_caches":[{"estimated_bytes":304305}],"session_cache_summary":{"estimated_bytes":0,"owners":0}}

class OwnershipTests(unittest.TestCase):
    def test_second_process_and_default_allocator_are_separate_blockers(self):
        r=report(fixture())
        self.assertEqual(r["admission"],"BLOCKED")
        self.assertTrue(r["gates"]["process_inventory_complete"])
        self.assertFalse(r["gates"]["single_visible_matching_target"])
        self.assertFalse(r["gates"]["allocator_exec_request_a2"])
        self.assertEqual(r["processes"]["other_matching_anon_bytes"],576933888)
        self.assertEqual(r["processes"]["other_matching_targets"][0]["tcp_close_wait"],1)
        self.assertEqual(r["session_observations"]["shared_cache_bytes"],304305)
    def test_exec_request_is_not_bypass_of_second_process_gate(self):
        v=fixture();v["allocator"]["arena_max_exec_env"]=2
        self.assertEqual(report(v)["admission"],"BLOCKED")
        v["container_processes"]["processes"].pop()
        self.assertEqual(report(v)["admission"],"EVIDENCE_GATES_PASS_NOT_PROMOTED")
    def test_partial_inventory_and_unknown_python_fail_closed(self):
        v=fixture();v["container_processes"]["processes"].pop()
        v["container_processes"]["status"]="partial"
        self.assertFalse(report(v)["gates"]["single_visible_matching_target"])
        v["container_processes"]["status"]="sampled"
        v["container_processes"]["processes"].append({"pid":9,"category":"Python","app":False})
        self.assertFalse(report(v)["gates"]["process_inventory_complete"])
    def test_runtime_only_conflicting_and_unavailable_startup_not_admitted(self):
        v=fixture();a=v["allocator"]
        a["arena_max_env"]=2
        self.assertEqual(report(v)["allocator"]["classification"],"RUNTIME_ONLY_NOT_ADMITTED")
        a["arena_max_exec_env"]=2;a["arena_tunable_exec"]=4
        self.assertEqual(report(v)["allocator"]["classification"],"DIFFERENT_OR_CONFLICTING_EXEC_REQUEST")
        a["arena_setting_origin"]="exec environment unavailable"
        self.assertEqual(report(v)["allocator"]["classification"],"STARTUP_EVIDENCE_UNAVAILABLE")
    def test_missing_data_not_zero(self):
        r=report({})
        self.assertEqual(r["admission"],"BLOCKED")
        self.assertIsNone(r["session_observations"]["shared_cache_bytes"])
        self.assertIsNone(r["container"]["used_bytes"])
