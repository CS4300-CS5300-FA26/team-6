Feature: Recently graded work on the dashboard
  As an enrolled college student
  I want to review my newly scored coursework on the primary overview page
  So that I can promptly check evaluation results as soon as grades are published

  Background:
    Given I have connected my Canvas account

  Scenario: Student views newly evaluated coursework
    Given I have newly published assignment scores
    When I navigate to the main dashboard
    Then I see my recent grades listed
    And I see the earned score alongside each entry

  Scenario: Multiple coursework items are evaluated
    Given I have multiple newly published assignment scores
    When I navigate to the main dashboard
    Then I see all recent feedback sorted by evaluation time, newest first

  Scenario: Student has no recent evaluations
    Given no new scores have been posted
    When I navigate to the main dashboard
    Then I see "No recently graded work"

  Scenario: Older grades are not shown as recent
    Given I have a score that was graded more than 14 days ago
    When I navigate to the main dashboard
    Then I do not see that assignment