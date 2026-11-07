Feature: Generate a study plan from selected assignments
  As a student
  I want to generate a study plan from selected assignments
  So that I can see when to work on the assignments I chose

  Scenario: Student generates a plan for selected assignments
    Given a student on the availability page with selected eligible assignments and availability
    When they generate a plan from the availability page
    Then the availability page shows availability, the assignment table, selected study sessions, and a generation notice
    And the availability page has no study session for the unselected assignment