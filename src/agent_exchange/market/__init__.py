"""The market layer — jobs, bids, reputation, bidding, hiring, discovery, recruiting."""

from .bidding import BiddingAgent, build_bidding_agents, relevance_probe, run_bidding
from .discovery import discover_pool
from .hiring import HiringPolicy, hire_and_notify, post_hiring
from .hiring_types import Hire, HiringDecision, ScoredBid, SelectionStrategy
from .marketplace import run_market_job
from .marketplace_types import AgentIdentity, MarketResult, RecruitedTeam
from .recruiting import recruit_team
from .reputation import JsonReputationStore
from .reputation_loop import WorkerOutcome, apply_outcomes, worker_outcomes
from .schema import Bid, Job, ReputationRecord, ReputationStore
from .selection import CoverageWithinBudget, KnapsackStrategy, score_bids, thompson_value

__all__ = ["Job", "Bid", "ReputationRecord", "ReputationStore", "JsonReputationStore",
           "relevance_probe", "BiddingAgent", "run_bidding", "build_bidding_agents",
           "thompson_value", "score_bids", "CoverageWithinBudget", "KnapsackStrategy",
           "ScoredBid", "Hire", "HiringDecision", "SelectionStrategy",
           "HiringPolicy", "post_hiring", "hire_and_notify",
           "AgentIdentity", "RecruitedTeam", "MarketResult",
           "discover_pool", "recruit_team", "run_market_job",
           "WorkerOutcome", "worker_outcomes", "apply_outcomes"]
