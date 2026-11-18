Feature: Course Hub assignments summary
  As an enrolled college student
  I want a summary of the selected course's assignments
  So that I can see upcoming or graded work without leaving the course page

  Scenario: Student views upcoming assignments for the selected course
    Given my Canvas account is connected
    And CS 4300 has upcoming assignments
    When I open the Course Hub
    And the CS 4300 tab and the Upcoming toggle are selected
    Then I see those CS 4300 assignments listed
    And I see the due date for each item

  Scenario: Student toggles to past and graded assignments
    Given I am on the Course Hub with CS 4300 selected
    And CS 4300 has at least one past or graded assignment
    When I click the Past/Graded toggle
    Then I see those past or graded CS 4300 assignments
    And I see the score next to each graded item

  Scenario: Student sees a view-all link
    Given I am on the Course Hub with CS 4300 selected
    And CS 4300 has 12 assignments
    When the assignments summary is shown
    Then I see a "View all 12 assignments" link

  Scenario: Selected course has no upcoming assignments
    Given I am on the Course Hub with a course selected
    And that course has no upcoming assignments
    When the Upcoming toggle is selected
    Then I see "No upcoming assignments"
