# Acceptance tests for the student availability Sprint 1 story.

Feature: Student availability

  # A student should be able to save valid availability.
  Scenario: Student enters valid availability
    Given I am logged in as a student
    When I create a valid availability period
    Then the availability period should be saved

  # A student should be able to update existing availability.
  Scenario: Student changes availability
    Given I am logged in as a student
    And I have an existing availability period
    When I update the availability period
    Then the updated availability should be saved

  # Invalid availability should be rejected.
  Scenario: Student enters invalid availability
    Given I am logged in as a student
    When I create an availability period with an end time before the start time
    Then the invalid availability should not be saved
    And I should receive an availability correction message
