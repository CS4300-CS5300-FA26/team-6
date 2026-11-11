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
