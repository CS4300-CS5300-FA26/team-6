Feature: Student assignment attachments
  As a student, I want to attach files to my assignments so my study material stays with its deadline.

  Scenario: Student uploads a file batch over 25 MB.
    Given I am viewing an assignment deadline
    When I upload a file(s) larger than 25 MB
    Then I see "File batch exceeds 25 MB limit"
    And no file is attached

  Scenario: Student attaches several files to an assignment
    Given I am viewing an assignment deadline
    When I attach several study files to the assignment
    Then I see my study files listed on that assignment

  Scenario: Attachments remain available after signing in again
    Given I am viewing an assignment deadline
    And I have attached several study files to the assignment
    When I sign in again
    Then I see my study files listed on that assignment

  Scenario: Student opens an attached course file.
    Given a document is linked to an assignment block
    When I click on the document from the calendar entry
    Then I can preview or download the resource immediately

  Scenario: Student removes one item among several attachments.
    Given several files are connected to a single deadline
    When I unbind a single target resource
    Then that specific item is removed from the view
    And all other linked materials stay attached to the task

  Scenario: Student aborts file deletion.
    Given a resource is saved on a calendar assignment
    When I start removing the item but dismiss the prompt
    Then the document remains present on the record card
