# Acceptance tests for Sprint 2 assignment effort estimation.

Feature: Assignment effort estimation

  # The application should estimate work when enough assignment data exists.
  Scenario: Application estimates effort for an assignment
    Given an assignment has enough information for an effort estimate
    When the application estimates the assignment effort
    Then an estimated amount of effort should be returned

  # Missing assignment information should fall back to manual entry.
  Scenario: Assignment does not contain enough information for an estimate
    Given an assignment is missing information required for effort estimation
    When the application attempts to estimate the assignment effort
    Then no automatic effort estimate should be returned
    And the student should be able to enter an estimate manually

  # The application should detect when the estimated work exceeds
  # the amount of study time currently available.
  Scenario: Estimated effort exceeds available study time
    Given an assignment requires more effort than the student has available
    When the application compares estimated effort with available study time
    Then the student should be notified that there is not enough available study time

  Scenario: Student changes estimated effort
    Given the student has an assignment with an estimated effort of 90 minutes
    When the student changes the effort estimate to 120 minutes
    Then the new effort estimate should be saved as 120 minutes
    And the updated effort estimate should be used for future scheduling