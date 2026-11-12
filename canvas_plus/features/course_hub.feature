Feature: Course Hub course tabs
  As an enrolled college student, I want a tab for each of my active courses,
  so that I can open the right course information and see my upcoming coursework.

  Background:
    Given I am a connected Course Hub student

  Scenario: One short-code tab for each active enrolled course
    When I open the Course Hub dashboard
    Then I see exactly these Course Hub tabs
      | course_code |
      | CS 4300     |
      | MATH 2150   |
      | ENGL 1310   |
      | HIST 1010   |

  Scenario: Stale and inactive courses are excluded
    Given Canvas also has ended, concluded, invited, and teacher courses
    When I open the Course Hub dashboard
    Then the excluded courses have no dashboard entry
    And opening any excluded course shows Course not found

  Scenario: Each tab opens exactly its Canvas course
    When I open the Course Hub dashboard
    Then each short-code tab links to its Canvas course ID and opens its matching heading

  Scenario: Course pages show only their own upcoming work
    Given every course has distinct upcoming assignments
    When I visit each active course page
    Then each page shows only that course's upcoming assignments

  Scenario: The dashboard combines upcoming work across active courses
    Given Canvas also has ended, concluded, invited, and teacher courses
    And every course has distinct upcoming assignments
    When I open the Course Hub dashboard
    Then I see upcoming assignments from every active course only

  Scenario: Zero active courses preserves the empty message
    Given I have zero active Course Hub courses
    When I open the Course Hub dashboard
    Then the Course Hub shows No current courses found and no course tabs

  Scenario: The course tab row is capped at twenty
    Given I have twenty-one active Course Hub courses
    When I open the Course Hub dashboard
    Then I see exactly twenty distinct course tabs

  Scenario: Repeat dashboard visits reuse the course list for one hour
    Given Course Hub course caching is enabled
    When I open the Course Hub dashboard
    And I reopen the Course Hub just before an hour has passed
    Then Canvas has been asked for courses only once
    And the courses are stored under the shared course-list cache key
    When I reopen the Course Hub after the hour has passed
    Then Canvas has been asked for courses twice

  Scenario: The dashboard reuses courses already cached by the assignments page
    Given Course Hub course caching is enabled
    And my courses are already cached under the assignments-page key
    When I open the Course Hub dashboard
    Then Canvas has not been asked for courses
    And I see exactly these Course Hub tabs
      | course_code |
      | CS 4300     |
      | MATH 2150   |
      | ENGL 1310   |
      | HIST 1010   |

  Scenario: The dashboard lists this week's work by local due day
    Given it is Wednesday, November 11 at 5:00 PM in Denver
    And my active courses have work due this week and one overdue assignment
    When I open the Course Hub dashboard
    Then the upcoming list reads "All courses · next 7 days"
    And I see this week's work grouped by due day
      | day                | course_code | title                             | course_name          | due      |
      | Today · Wed Nov 11 | CS 4300     | Sprint 4 retrospective            | Software Engineering | 11:59 PM |
      | Thursday · Nov 12  | MATH 2150   | Problem set 7                     | Discrete Mathematics | 9:00 AM  |
      | Thursday · Nov 12  | ENGL 1310   | Annotated bibliography draft      | Rhetoric and Writing | 11:59 PM |
      | Monday · Nov 16    | HIST 1010   | Reading response: Silk Road trade | World History        | 5:00 PM  |

  Scenario: The dashboard keeps to the next seven days and links to all work
    Given it is Wednesday, November 11 at 5:00 PM in Denver
    And my active courses have work due this week and one overdue assignment
    When I open the Course Hub dashboard
    Then I don't see "Sprint 3 demo" on the dashboard
    And the dashboard links to the assignments page with "View all 5 assignments →"
