# Acceptance tests for Sprint 2 assignment effort estimation.

Feature: Assignment effort estimation

  # The application should estimate work when enough assignment data exists.
  Scenario: Application estimates effort for an assignment
    Given an assignment has enough information for an effort estimate
    When the application estimates the assignment effort
    Then an estimated amount of effort should be returned

  # Missing assignment information should fall back to manual entry.
  Scenario: Assignment does not contain enough information for an estimate
    Given the assignment is missing information needed for an effort estimate
    When the application attempts to estimate the assignment effort
    Then no automatic effort estimate should be created
    And the student can enter a manual estimate of 60 minutes
    And the manual effort estimate should be saved as 60 minutes

  #Student changes the effort manually
  Scenario: Student changes estimated effort through the manual entry form
    Given the student has an assignment with an estimated effort of 90 minutes
    When the student changes the effort estimate to 120 minutes through the edit page
    Then the new effort estimate should be saved as 120 minutes
    