Feature: Current course list
  As an enrolled college student, I want to see a list of my current courses,
  so that I can find a course without searching through old semesters.

  Scenario: Only current courses are listed
    Given my Canvas account is connected
    And I am enrolled in a course this semester and a course from a past semester
    When I open Courses from the sidebar
    Then I see this semester's course
    And I don't see the past semester's course

  Scenario: No current courses
    Given my Canvas account is connected
    And I have no current courses
    When I open Courses
    Then I see "No current courses found"

  Scenario Outline: Courses can't be loaded
    Given <situation>
    When I open Courses
    Then I see "<message>"

    Examples:
      | situation                          | message                            |
      | my Canvas account is not connected | Connect Canvas to see your courses |
      | my Canvas connection has expired   | Please reconnect                   |
      | Canvas is down                     | Please try again                   |
