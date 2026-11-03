Feature: Study plan on the availability page
  As an enrolled college student
  I want to see my generated study plan next to my availability
  So that I know when to work on each assignment

  Scenario: Student views their study plan
    Given I am logged in as a student
    And my most recent study plan has a session for "HW3" on 2026-11-05 from 2:00 PM to 3:30 PM
    And my most recent study plan has a session for "HW3" on 2026-11-06 from 9:00 AM to 10:00 AM
    When I open my availability page
    Then I see a study session for "HW3" on 2026-11-05 from 2:00 PM to 3:30 PM
    And I see a study session for "HW3" on 2026-11-06 from 9:00 AM to 10:00 AM

  Scenario: Student picks a specific day
    Given I am logged in as a student
    And my most recent study plan has a session for "HW3" on 2026-11-05 from 2:00 PM to 3:30 PM
    And my most recent study plan has a session for "Lab 4" on 2026-11-06 from 9:00 AM to 10:00 AM
    When I open my availability page for "2026-11-05"
    Then I see a study session for "HW3"
    And I do not see a study session for "Lab 4"

  Scenario: The plan covers several assignments
    Given I am logged in as a student
    And my most recent study plan has a session for "HW3" on 2026-11-05 from 2:00 PM to 3:00 PM
    And my most recent study plan has a session for "Lab 4" on 2026-11-05 from 3:00 PM to 4:00 PM
    And my most recent study plan has a session for "Essay 2" on 2026-11-05 from 4:00 PM to 5:00 PM
    When I open my availability page
    Then I see these study sessions:
      | assignment | time               |
      | HW3        | 2:00 PM to 3:00 PM |
      | Lab 4      | 3:00 PM to 4:00 PM |
      | Essay 2    | 4:00 PM to 5:00 PM |

  Scenario: Student has not generated a study plan
    Given I am logged in as a student
    And I have not generated a study plan
    When I open my availability page
    Then I am told I have no study plan yet

  Scenario: Student sees only their most recent study plan
    Given I am logged in as a student
    And I had an older study plan with a session for "Old Essay"
    And my most recent study plan has a session for "Lab 4"
    When I open my availability page
    Then I see a study session for "Lab 4"
    And I do not see a study session for "Old Essay"

  # Abuse case: the other student's plan is newer than mine, so a "latest plan"
  # lookup that forgets whose plan it is would show theirs.
  Scenario: Another student's study plan never appears on my page
    Given I am logged in as a student
    And my most recent study plan has a session for "Lab 4"
    And another student made a study plan after mine with a session for "Their Thesis"
    When I open my availability page
    Then I see a study session for "Lab 4"
    And I do not see a study session for "Their Thesis"

  Scenario: Student reaches their study plan from the sidebar
    Given I am logged in as a student
    And my most recent study plan has a session for "Lab 4"
    When I open Study Plan from the sidebar
    Then I see a study session for "Lab 4"

  Scenario: Student picks a day with nothing scheduled
    Given I am logged in as a student
    And my most recent study plan has a session for "Lab 4"
    When I open my availability page for "2026-11-10"
    Then I am told I have no study sessions that day

  Scenario Outline: Student asks for a day that is not a real date
    Given I am logged in as a student
    And my most recent study plan has a session for "Lab 4"
    When I open my availability page for "<day>"
    Then I am told that day is not a valid date

    Examples:
      | day        |
      | 2026-02-30 |
      | not-a-date |
