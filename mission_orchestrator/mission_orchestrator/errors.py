class MissionContractError(Exception):
    """Base exception for canonical mission contract failures."""


class MissionValidationError(MissionContractError):
    pass


class MissionValidationPipelineError(MissionValidationError):
    def __init__(self, message: str, *, phase: str, check_id: str):
        super().__init__(message)
        self.phase = phase
        self.check_id = check_id


class MissionIdempotencyConflict(MissionContractError):
    pass


class MissionNotFound(MissionContractError):
    pass


class MissionStateConflict(MissionContractError):
    pass


class MissionIllegalTransition(MissionContractError):
    pass


class MissionScopeContractConflict(MissionContractError):
    pass


class MissionScopeContractNotFound(MissionContractError):
    pass


class MissionGovernanceBindingConflict(MissionContractError):
    pass


class MissionGovernanceBindingNotFound(MissionContractError):
    pass


class MissionGovernanceUnavailable(MissionContractError):
    pass


class MissionGovernanceProtocolError(MissionContractError):
    pass


class MissionAuthorizationConflict(MissionContractError):
    pass


class MissionAuthorizationBindingNotFound(MissionContractError):
    pass


class MissionAuthorizationFailClosed(MissionContractError):
    pass


class MissionTaskConflict(MissionContractError):
    pass


class MissionTaskNotFound(MissionContractError):
    pass


class MissionTaskRoutingFailClosed(MissionContractError):
    pass


class MissionSubsystemUnavailable(MissionContractError):
    pass


class MissionSubsystemProtocolError(MissionContractError):
    pass


class MissionConcurrencyConflict(MissionContractError):
    pass


class MissionCommandConflict(MissionContractError):
    pass


class MissionCommandNotFound(MissionContractError):
    pass


class MissionLifecycleGuardRejected(MissionContractError):
    pass


class MissionVersionObservationUnavailable(MissionContractError):
    pass


class MissionRepositoryIntegrityError(MissionContractError):
    pass


class MissionEventNotFound(MissionContractError):
    pass


class MissionEventIntegrityError(MissionContractError):
    pass


class MissionPlanContractConflict(MissionContractError):
    pass


class MissionPlanContractNotFound(MissionContractError):
    pass


class MissionPlanContractGuardRejected(MissionContractError):
    pass


class MissionPlannerInputSnapshotConflict(MissionContractError):
    pass


class MissionPlannerInputSnapshotNotFound(MissionContractError):
    pass


class MissionPlannerInputSnapshotGuardRejected(MissionContractError):
    pass


class MissionTaskDecompositionConflict(MissionContractError):
    pass


class MissionTaskDecompositionNotFound(MissionContractError):
    pass


class MissionTaskDecompositionGuardRejected(MissionContractError):
    pass


class MissionPlannedTaskNotFound(MissionContractError):
    pass


class MissionTaskDependencyGraphConflict(MissionContractError):
    pass


class MissionTaskDependencyGraphNotFound(MissionContractError):
    pass


class MissionTaskDependencyGraphGuardRejected(MissionContractError):
    pass


class MissionPlannerGenerationConflict(MissionContractError):
    pass


class MissionPlannerGenerationNotFound(MissionContractError):
    pass


class MissionPlannerGenerationGuardRejected(MissionContractError):
    pass

class MissionPlanValidationConflict(MissionContractError):
    pass


class MissionPlanValidationNotFound(MissionContractError):
    pass


class MissionPlanValidationGuardRejected(MissionContractError):
    pass

class MissionPlanVersioningConflict(MissionContractError):
    pass


class MissionPlanVersioningNotFound(MissionContractError):
    pass


class MissionPlanVersioningGuardRejected(MissionContractError):
    pass

class MissionTaskReadinessProjectionConflict(MissionContractError):
    pass


class MissionTaskReadinessProjectionNotFound(MissionContractError):
    pass


class MissionTaskReadinessProjectionGuardRejected(MissionContractError):
    pass

class MissionPlanningRecoveryConflict(MissionContractError):
    pass


class MissionPlanningRecoveryNotFound(MissionContractError):
    pass


class MissionPlanningRecoveryGuardRejected(MissionContractError):
    pass

class SubsystemRegistryIntegrityError(MissionContractError):
    pass


class SubsystemNotFound(MissionContractError):
    pass


class SubsystemCapabilityNotFound(MissionContractError):
    pass


class MissionTaskRoutingIntentConflict(MissionContractError):
    pass


class MissionTaskRoutingIntentNotFound(MissionContractError):
    pass


class MissionTaskRoutingIntentGuardRejected(MissionContractError):
    pass



class MissionTaskRoutingEligibilityConflict(MissionContractError):
    pass


class MissionTaskRoutingEligibilityNotFound(MissionContractError):
    pass


class MissionTaskRoutingEligibilityGuardRejected(MissionContractError):
    pass


class MissionTaskRouteSelectionConflict(MissionContractError):
    pass


class MissionTaskRouteSelectionNotFound(MissionContractError):
    pass


class MissionTaskRouteSelectionGuardRejected(MissionContractError):
    pass


class MissionDelegationAuthorizationConflict(MissionContractError):
    pass


class MissionDelegationAuthorizationNotFound(MissionContractError):
    pass


class MissionDelegationAuthorizationGuardRejected(MissionContractError):
    pass


class MissionTaskDelegationConflict(MissionContractError):
    pass


class MissionTaskDelegationNotFound(MissionContractError):
    pass


class MissionTaskDelegationGuardRejected(MissionContractError):
    pass


class MissionDelegationDeliveryConflict(MissionContractError):
    pass


class MissionDelegationDeliveryNotFound(MissionContractError):
    pass


class MissionDelegationDeliveryGuardRejected(MissionContractError):
    pass


class MissionDelegationRecoveryControlConflict(MissionContractError):
    pass


class MissionDelegationRecoveryControlNotFound(MissionContractError):
    pass


class MissionDelegationRecoveryControlGuardRejected(MissionContractError):
    pass

class MissionRoutingDelegationRecoveryConflict(MissionContractError):
    pass


class MissionRoutingDelegationRecoveryNotFound(MissionContractError):
    pass


class MissionRoutingDelegationRecoveryGuardRejected(MissionContractError):
    pass


class MissionExecutionDispatchConflict(MissionContractError):
    pass


class MissionExecutionDispatchNotFound(MissionContractError):
    pass


class MissionExecutionDispatchGuardRejected(MissionContractError):
    pass


class MissionDispatchEligibilityConflict(MissionContractError):
    pass


class MissionDispatchEligibilityNotFound(MissionContractError):
    pass


class MissionDispatchEligibilityGuardRejected(MissionContractError):
    pass


class MissionPreDispatchGovernanceConflict(MissionContractError):
    pass


class MissionPreDispatchGovernanceNotFound(MissionContractError):
    pass


class MissionPreDispatchGovernanceGuardRejected(MissionContractError):
    pass

class MissionExecutionAttemptConflict(MissionContractError):
    pass


class MissionExecutionAttemptNotFound(MissionContractError):
    pass


class MissionExecutionAttemptGuardRejected(MissionContractError):
    pass

class MissionExecutionDeliveryConflict(MissionContractError):
    pass


class MissionExecutionDeliveryNotFound(MissionContractError):
    pass


class MissionExecutionDeliveryGuardRejected(MissionContractError):
    pass

class MissionExecutionRunningProjectionConflict(MissionContractError):
    pass


class MissionExecutionRunningProjectionNotFound(MissionContractError):
    pass


class MissionExecutionRunningProjectionGuardRejected(MissionContractError):
    pass

class MissionExecutionResultCaptureConflict(MissionContractError):
    pass


class MissionExecutionResultCaptureNotFound(MissionContractError):
    pass


class MissionExecutionResultCaptureGuardRejected(MissionContractError):
    pass

class MissionExecutionTerminationControlConflict(MissionContractError):
    pass


class MissionExecutionTerminationControlNotFound(MissionContractError):
    pass


class MissionExecutionTerminationControlGuardRejected(MissionContractError):
    pass


class MissionExecutionOutcomePropagationConflict(MissionContractError):
    pass


class MissionExecutionOutcomePropagationNotFound(MissionContractError):
    pass


class MissionExecutionOutcomePropagationGuardRejected(MissionContractError):
    pass

class MissionExecutionRecoveryConflict(MissionContractError):
    pass


class MissionExecutionRecoveryNotFound(MissionContractError):
    pass


class MissionExecutionRecoveryGuardRejected(MissionContractError):
    pass

class MissionTaskOutcomeConflict(MissionContractError):
    pass


class MissionTaskOutcomeNotFound(MissionContractError):
    pass


class MissionTaskOutcomeGuardRejected(MissionContractError):
    pass

class MissionTaskTerminalityEligibilityConflict(MissionContractError):
    pass


class MissionTaskTerminalityEligibilityNotFound(MissionContractError):
    pass


class MissionTaskTerminalityEligibilityGuardRejected(MissionContractError):
    pass

class MissionTaskEvidenceBindingConflict(MissionContractError):
    pass


class MissionTaskEvidenceBindingNotFound(MissionContractError):
    pass


class MissionTaskEvidenceBindingGuardRejected(MissionContractError):
    pass

class MissionTaskCompletionConflict(MissionContractError):
    pass


class MissionTaskCompletionNotFound(MissionContractError):
    pass


class MissionTaskCompletionGuardRejected(MissionContractError):
    pass


class MissionOutcomeAggregationConflict(MissionContractError):
    pass


class MissionOutcomeAggregationNotFound(MissionContractError):
    pass


class MissionOutcomeAggregationGuardRejected(MissionContractError):
    pass


class MissionSuccessEvaluationConflict(MissionContractError):
    pass


class MissionSuccessEvaluationNotFound(MissionContractError):
    pass


class MissionSuccessEvaluationGuardRejected(MissionContractError):
    pass


class MissionCompletionReadinessConflict(MissionContractError):
    pass


class MissionCompletionReadinessNotFound(MissionContractError):
    pass


class MissionCompletionReadinessGuardRejected(MissionContractError):
    pass

class MissionVerifiedCompletionConflict(MissionContractError):
    pass


class MissionVerifiedCompletionNotFound(MissionContractError):
    pass


class MissionVerifiedCompletionGuardRejected(MissionContractError):
    pass
class MissionOutcomeRecoveryConflict(MissionContractError):
    pass


class MissionOutcomeRecoveryNotFound(MissionContractError):
    pass


class MissionOutcomeRecoveryGuardRejected(MissionContractError):
    pass

class MissionAdaptationReplanConflict(MissionContractError):
    pass


class MissionAdaptationReplanNotFound(MissionContractError):
    pass


class MissionAdaptationReplanGuardRejected(MissionContractError):
    pass


class MissionAdaptationTriggerClassificationConflict(MissionContractError):
    pass


class MissionAdaptationTriggerClassificationNotFound(MissionContractError):
    pass


class MissionAdaptationTriggerClassificationGuardRejected(MissionContractError):
    pass


class MissionReplanEligibilityGovernanceConflict(MissionContractError):
    pass


class MissionReplanEligibilityGovernanceNotFound(MissionContractError):
    pass


class MissionReplanEligibilityGovernanceGuardRejected(MissionContractError):
    pass


class MissionReplanSnapshotConflict(MissionContractError):
    pass


class MissionReplanSnapshotNotFound(MissionContractError):
    pass


class MissionReplanSnapshotGuardRejected(MissionContractError):
    pass


class MissionReplanCandidateConflict(MissionContractError):
    pass


class MissionReplanCandidateNotFound(MissionContractError):
    pass


class MissionReplanCandidateGuardRejected(MissionContractError):
    pass


class MissionReplanValidationConflict(MissionContractError):
    pass


class MissionReplanValidationNotFound(MissionContractError):
    pass


class MissionReplanValidationGuardRejected(MissionContractError):
    pass


class MissionReplanCommitConflict(MissionContractError):
    pass


class MissionReplanCommitNotFound(MissionContractError):
    pass


class MissionReplanCommitGuardRejected(MissionContractError):
    pass


class MissionReplanHandoffConflict(MissionContractError):
    pass


class MissionReplanHandoffNotFound(MissionContractError):
    pass


class MissionReplanHandoffGuardRejected(MissionContractError):
    pass

class MissionReplanRecoveryConflict(MissionContractError):
    pass


class MissionReplanRecoveryNotFound(MissionContractError):
    pass


class MissionReplanRecoveryGuardRejected(MissionContractError):
    pass


class MissionCTIFeedbackNotFound(MissionContractError):
    pass


class MissionCTIFeedbackRejected(MissionContractError):
    pass


class MissionCTIFeedbackUnavailable(MissionContractError):
    pass
