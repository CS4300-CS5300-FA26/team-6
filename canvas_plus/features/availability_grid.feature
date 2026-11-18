Feature: Weekly availability grid on the Study Plan page
  As a student
  I want to mark when I am free by selecting hour blocks on a weekly grid
  So that entering my availability is quick instead of filling in a form for every time period

  # Today is fixed in a past year, so code that reads the real clock instead
  # of "today" cannot pass by accident. This week runs Monday, November 16 to
  # Sunday, November 22, 2020; day names below mean days in this week.
  #
  # "On <day> I am available only from ..." lists every period that day has,
  # so an extra, missing, or unmerged period fails the scenario.
  Background:
    Given today is Wednesday, November 18, 2020
    And I am logged in as a student

  Scenario: Selecting blocks saves my availability
    Given I have no availability this week
    When I select the Thursday 10 AM and 11 AM blocks and save
    Then on Thursday I am available only from 10:00 AM to 12:00 PM

  Scenario: Separate blocks are saved as separate periods
    Given I have no availability this week
    When I select the Thursday 10 AM and 2 PM blocks and save
    Then on Thursday I am available only from 10:00 AM to 11:00 AM and from 2:00 PM to 3:00 PM

  Scenario: My saved availability is shown on the grid
    Given I am available on Friday from 2:00 PM to 4:00 PM
    When I view the Study Plan page
    Then the Friday 2 PM and 3 PM blocks are selected
    And the Friday 4 PM block is not selected

  Scenario: Deselecting a block removes that time
    Given I am available on Thursday from 10:00 AM to 12:00 PM
    When I deselect the Thursday 11 AM block and save
    Then on Thursday I am available only from 10:00 AM to 11:00 AM

  Scenario: Days that have already passed cannot be changed
    When I view the Study Plan page
    Then the Monday and Tuesday blocks cannot be selected
    And the Wednesday blocks can be selected

  # The page disables past days, but a request can still include them. The
  # Thursday block shows the request was saved and only Monday was dropped.
  Scenario: Blocks on days that have passed are ignored
    When I submit the Monday 10 AM block together with the Thursday 10 AM block
    Then I have no availability on Monday
    And on Thursday I am available only from 10:00 AM to 11:00 AM

  Scenario: Availability on days that have passed survives a save
    Given I am available on Monday from 10:00 AM to 12:00 PM
    When I select the Thursday 10 AM block and save
    Then on Monday I am available only from 10:00 AM to 12:00 PM
    And on Thursday I am available only from 10:00 AM to 11:00 AM

  Scenario: Availability that does not fill whole hours is kept
    Given I am available on Thursday from 9:30 AM to 10:15 AM
    When I select the Friday 2 PM block and save
    Then on Thursday I am available only from 9:30 AM to 10:15 AM
    And on Friday I am available only from 2:00 PM to 3:00 PM

  Scenario: Availability outside the grid's hours is kept
    Given I am available on Thursday from 9:00 PM to 10:00 PM
    When I select the Thursday 10 AM block and save
    Then on Thursday I am available only from 10:00 AM to 11:00 AM and from 9:00 PM to 10:00 PM

  Scenario: Blocks outside this week are ignored
    When I submit a block for next Monday together with the Thursday 10 AM block
    Then I have no availability on next Monday
    And on Thursday I am available only from 10:00 AM to 11:00 AM

  # Abuse case: a lookup that forgets whose availability it is would show theirs.
  Scenario: Another student's availability is not shown
    Given another student is available on Thursday from 10:00 AM to 12:00 PM
    When I view the Study Plan page
    Then no blocks are selected

  # Abuse case: saving replaces a day's periods, so a save that forgets
  # whose periods it is replacing would delete another student's time.
  Scenario: Saving does not change another student's availability
    Given another student is available on Thursday from 10:00 AM to 12:00 PM
    When I select the Thursday 2 PM block and save
    Then on Thursday the other student is available only from 10:00 AM to 12:00 PM
    And on Thursday I am available only from 2:00 PM to 3:00 PM

  # Side-by-side placement is CSS, which this test cannot see; the screenshot covers it.
  Scenario: Layout matches the wireframe
    When I view the Study Plan page
    Then I see My Availability with a Monday to Sunday grid from 8 AM to 8 PM
    And I see My Availability and then Generated Plan
