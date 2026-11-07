Feature: Generate a study plan from selected assignments
  As a student
  I want to generate a study plan from selected assignments
  So that I can see when to work on the assignments I chose

  Scenario: Student generates a plan for selected assignments
    Given a student with selected eligible assignments and availability
    When they generate a plan
    Then the study plan shows the selected assignments and generation notice
    And the study plan omits the unselected assignment