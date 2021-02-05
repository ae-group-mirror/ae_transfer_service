""" common setup for root and portions (modules or sub-packages) of the ae namespace package.

# THIS FILE IS EXCLUSIVELY MAINTAINED IN THE NAMESPACE ROOT PACKAGE. CHANGES HAVE TO BE DONE THERE.
# All changes will be deployed automatically to all the portions of this namespace package.

This file get run by each portion of this namespace package for builds (sdist/bdist_wheel)
and installation (install); also gets imported by the root package (for the globals defined
here) for documentation builds (docs/conf.py), common file deploys and commit preparations.
"""
import pprint
import setuptools

from de.core import file_content, namespace_env_vars


namespace_name = 'ae'


if __name__ == "__main__":
    nev = namespace_env_vars(namespace_name)
    package_name = nev['package_name']

    setup_kwargs = dict(
        name=package_name,              # or pip install name (nev['pip_name']) or import name (nev['import_name'])
        version=nev['package_version'],
        author="Andi Ecker",
        author_email="aecker2@gmail.com",
        description=package_name + " portion of python application environment namespace package",
        license=nev['portion_license'],
        long_description=file_content("README.md"),
        long_description_content_type="text/markdown",
        url=f"{nev['repo_root']}/{package_name}",
        # kwargs that are don't needed for native/implicit namespace packages:
        # - namespace_packages=[namespace_name],
        # - packages=setuptools.find_packages(),
        # find namespace portion packages resulting in:
        # - ['ae'] for a (single) portion module.
        #   * using instead hardcoded packages=[] results in incomplete package
        #   * using ['ae.literal'] `setup sdist bdist_wheel` fails with "package directory 'ae/literal' does not exist"
        # - ['ae.<sub-package1-name>', ...] for sub-package(s)
        packages=setuptools.find_namespace_packages(include=nev['find_packages_include']),
        # include_package_data=True,    # uncommenting this line results in NOT including package resources into sdist
        package_data={'': nev['package_resources']},
        zip_safe=not bool(nev['package_resources']),    # resources have to be available as separate files
        python_requires=">=3.6",
        install_requires=nev['install_require'],
        setup_requires=nev['setup_require'],
        extras_require={
            'docs': nev['docs_require'],
            'tests': nev['tests_require'],
            'dev': nev['docs_require'] + nev['tests_require'],
        },
        classifiers=[
            "Development Status :: 1 - Planning",
            "Natural Language :: English",
            "Operating System :: OS Independent",
            "Programming Language :: Python",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.6",
            "License :: " + nev['portion_license'],
            "Operating System :: OS Independent",
            "Topic :: Software Development :: Libraries :: Application Frameworks",
        ],
        keywords=[
            'productivity',
            'application',
            'environment',
            'configuration',
            'development',
        ]
    )
    print("#  EXECUTING SETUPTOOLS SETUP #################################")
    print(pprint.pformat(setup_kwargs, indent=3, width=75, compact=True))
    setuptools.setup(**setup_kwargs)
    print("#  FINISHED SETUPTOOLS SETUP  #################################")
