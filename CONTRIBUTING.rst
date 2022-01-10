
..
    THIS FILE IS EXCLUSIVELY MAINTAINED by the project aedev_tpl_project V0.3.4 

contributing
============

we want to make it as easy and fun as possible for you to contribute to this project.


reporting bugs
--------------

before you create a new issue, please check to see if you are using the latest version of this project; the bug may
already be resolved.

also search for similar problems in the issue tracker; it may already be an identified problem.

include as much information as possible into the issue description, at least:

1. version numbers (of Python and any involved packages).
2. small self-contained code example that reproduces the bug.
3. steps to reproduce the error.
4. any traceback/error/log messages shown.


requesting new features
-----------------------

1. provide a clear and detailed explanation of the feature you want and why it's important to add.
2. if you are able to implement the feature yourself (refer to the `contribution steps`_ section below).


contribution steps
------------------

thanks for your contribution -- we'll get your merge request reviewed. you should also review other merge requests, just
like other developers will review yours and comment on them. based on the comments, you should address them. once the
reviewers approve, the maintainers will merge.

before you start make sure you have a `GitLab account <https://gitlab.com/users/sign_up>`__.

contribution can be done either with the :mod:`git-repo-manager tool <aedev.git_repo_manager>` or directly by using
``git`` and the ``Gitlab`` website.


using the git repository manager `grm`
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. fork and clone the repository of this project to your computer

   in your console change the working directory to your project's parent folder. then run the following command with
   the <new_feature_or_fix> part replaced by an appropriate branch name, describing shortly your contribution::

      grm fork ae-group/ae_transfer_service

   .. note::
      the fork action of ``grm`` will also add the forked repository as the remote ``upstream`` to your local
      repository. additionally you can specify the option ``--branch <new_feature_or_fix>`` to create a new git branch.

2. code

   implement the new feature or the bug fix; include tests, and ensure they pass.

3. publish your changes

   before you initiate a push/merge request against the Gitlab server, create a `.commit_msg.txt` file in the
   working tree root of your project, containing a short summary in the first line followed with a blank line and then
   more detailed descriptions of the change.

   .. hint::
      the `.commit_msg.txt` file can be created with any text editor or by running ``grm prepare`` command. as
      the file content please provide a detailed, clear, and complete description of your changes! for changes,
      initiated by a bug fix please include the issue number (in the format ``fixes #<issue-number>``) in the commit
      summary. you may use ``Markdown`` syntax for simple styling.

   to finally commit and upload your changes run the following three commands in the root folder of your project::

      grm commit
      grm push
      grm request

   .. hint::
      these ``grm`` commands are first running all your unit tests. if they pass then a new git commit, including your
      changes, will be created. then the commit will be pushed to your ``origin`` remote repository (your fork) and
      finally creating a merge/pull request against the ``upstream`` remote repository (the forked one).


more detailed information of the features of the ``grm`` tool are available within the `documentation of the aedev
namespace <https://aedev.readthedocs.io/en/latest/man/git_repo_manager.html>`__.


using `git` and `Gitlab`
^^^^^^^^^^^^^^^^^^^^^^^^

alternatively to the ``grm`` tool you could directly use the `git command suite <https://git-scm.com/docs>`__ and the
`Gitlab website <https://gitlab.com>`__ to achieve the same (with a lot more of typing and fiddling ;-):

1. fork the `upstream repository <https://gitlab.com/ae-group/ae_transfer_service>`__ into your user account.

2. clone your forked repo as ``origin`` remote to your computer, and add an ``upstream`` remote for the destination
   repo by running the following commands in the console of your local machine::

      git clone https://gitlab.com/<YourGitLabUserName>/ae_transfer_service.git
      git remote add upstream https://gitlab.com/ae-group/ae_transfer_service.git

3. checkout out a new local feature branch and update it to the latest version of the ``develop`` branch::

      git checkout -b <new_feature_or_fix_branch_name> develop
      git pull --rebase upstream develop

   please keep your code clean by staying current with the ``develop`` branch, where code will be merged. if you
   find another bug, please fix it in a separated branch instead.

4. push the branch to your fork. treat it as a backup::

      git push origin <new_feature_or_fix_branch_name>

5. code

   implement the new feature or the bug fix; include tests, and ensure they pass.

6. check

   run the basic code style and typing checks locally (pylint, mypy and flake8) before you commit.

7. commit

   for every commit please write a short summary in the first line followed with a blank line and then more detailed
   descriptions of the change. for bug fixes please include any issue number (in the format #nnn) in your summary::

      git commit -m "issue #123: put change summary here (can be a issue title)"

   .. note::
      **never leave the commit message blank!** provide a detailed, clear, and complete description of your changes!

8. publish your changes (prepare a Merge Request)

   before submitting a `merge request <https://docs.gitlab.com/ce/workflow/forking_workflow.html#merging-upstream>`__,
   update your branch to the latest code::

      git pull --rebase upstream develop

   if you have made many commits, we ask you to squash them into atomic units of work. most issues should have one
   commit only, especially bug fixes, which makes them easier to back port::

      git checkout develop
      git pull --rebase upstream develop
      git checkout <new_feature_or_fix_branch_name>
      git rebase -i develop

   push changes to your fork::

      git push -f

9. issue/make a GitLab Merge Request:

   * navigate to your fork where you just pushed to
   * click `Merge Request`
   * in the branch field write your feature branch name (this is filled with your default branch name)
   * click `Update Commit Range`
   * ensure the changes you implemented are included in the `Commits` tab
   * ensure that the `Files Changed` tab incorporate all of your changes
   * fill in some details about your potential patch including a meaningful title
   * click `New merge request`.


deployment to PYPI
------------------

the deployment of a new/changed project will automatically be initiated by the GitLab CI, using the two
protected vars ``PYPI_USERNAME`` and ``PYPI_PASSWORD`` (marked as masked) from the users group of this namespace, in
order to provide the user name and password of the maintainers PYPI account (on Gitlab.com at Settings/CI_CD/Variables).


useful links and resources
--------------------------

- `General GitLab documentation <https://docs.gitlab.com/ce/>`__
- `GitLab workflow documentation <https://docs.gitlab.com/ee/user/project/repository/forking_workflow.html>`__
- grm (git repository manager)
  :mod:`project repository <aedev.git_repo_manager>`  and
  `documentation <https://aedev.readthedocs.io/en/latest/man/git_repo_manager.html>`__
